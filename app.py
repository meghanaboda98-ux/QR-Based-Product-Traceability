
import os
import sqlite3
import uuid
from datetime import datetime

import qrcode
from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, jsonify, abort
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, "traceability.db")
QR_FOLDER = os.path.join(BASE_DIR, "static", "qr_codes")

os.makedirs(QR_FOLDER, exist_ok=True)

app = Flask(__name__)
app.secret_key = "change-this-secret-key"


# ==========================================
# 1. DATABASE CONNECTION
# ==========================================

def get_db():
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    return connection


# ==========================================
# 2. DATABASE INITIALIZATION
# ==========================================

def initialize_database():

    connection = get_db()

    connection.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_code TEXT UNIQUE NOT NULL,
            product_name TEXT NOT NULL,
            variety TEXT,
            farmer_name TEXT NOT NULL,
            farmer_phone TEXT,
            fpo_name TEXT,
            quantity REAL,
            unit TEXT,
            village TEXT,
            district TEXT,
            state TEXT,
            harvest_date TEXT,
            collection_date TEXT,
            quality_notes TEXT,
            created_at TEXT NOT NULL
        )
    """)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS trace_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_code TEXT NOT NULL,
            event_type TEXT NOT NULL,
            location TEXT,
            description TEXT,
            updated_by TEXT,
            event_date TEXT NOT NULL,
            FOREIGN KEY (batch_code)
                REFERENCES products(batch_code)
        )
    """)

    connection.commit()
    connection.close()


# ==========================================
# 3. GENERATE UNIQUE BATCH ID
# ==========================================

def generate_batch_code():
    return "AG-" + uuid.uuid4().hex[:10].upper()


# ==========================================
# 4. GENERATE QR CODE
# ==========================================

def generate_qr_code(batch_code):

    trace_url = url_for(
        "trace_product",
        code=batch_code,
        _external=True
    )

    qr = qrcode.make(trace_url)

    image_path = os.path.join(
        QR_FOLDER,
        batch_code + ".png"
    )

    qr.save(image_path)

    return image_path


# ==========================================
# 5. HOME / DASHBOARD
# ==========================================

@app.route("/")
def home():

    connection = get_db()

    products = connection.execute("""
        SELECT * FROM products
        ORDER BY id DESC
    """).fetchall()

    total_products = connection.execute(
        "SELECT COUNT(*) FROM products"
    ).fetchone()[0]

    total_events = connection.execute(
        "SELECT COUNT(*) FROM trace_events"
    ).fetchone()[0]

    connection.close()

    return render_template(
        "index.html",
        products=products,
        total_products=total_products,
        total_events=total_events
    )


# ==========================================
# 6. PRODUCT REGISTRATION
# ==========================================

@app.route("/register", methods=["GET", "POST"])
def register_product():

    if request.method == "POST":

        product_name = request.form.get(
            "product_name", ""
        ).strip()

        farmer_name = request.form.get(
            "farmer_name", ""
        ).strip()

        if not product_name or not farmer_name:
            flash(
                "Product name and farmer name are required.",
                "error"
            )
            return redirect(url_for("register_product"))

        batch_code = generate_batch_code()

        connection = get_db()

        try:

            connection.execute("""
                INSERT INTO products (
                    batch_code,
                    product_name,
                    variety,
                    farmer_name,
                    farmer_phone,
                    fpo_name,
                    quantity,
                    unit,
                    village,
                    district,
                    state,
                    harvest_date,
                    collection_date,
                    quality_notes,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                batch_code,
                product_name,
                request.form.get("variety", ""),
                farmer_name,
                request.form.get("farmer_phone", ""),
                request.form.get("fpo_name", ""),
                request.form.get("quantity") or None,
                request.form.get("unit", "kg"),
                request.form.get("village", ""),
                request.form.get("district", ""),
                request.form.get("state", ""),
                request.form.get("harvest_date", ""),
                request.form.get("collection_date", ""),
                request.form.get("quality_notes", ""),
                datetime.now().isoformat(timespec="seconds")
            ))

            connection.execute("""
                INSERT INTO trace_events (
                    batch_code,
                    event_type,
                    location,
                    description,
                    updated_by,
                    event_date
                )
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                batch_code,
                "Product Registered",
                request.form.get("village", ""),
                "Product registered by farmer/FPO.",
                farmer_name,
                datetime.now().isoformat(timespec="seconds")
            ))

            connection.commit()

        except sqlite3.Error as error:

            connection.rollback()
            connection.close()

            flash("Database error: " + str(error), "error")

            return redirect(url_for("register_product"))

        connection.close()

        generate_qr_code(batch_code)

        flash(
            "Product registered and QR code generated successfully.",
            "success"
        )

        return redirect(
            url_for("product_details", code=batch_code)
        )

    return render_template("register.html")


# ==========================================
# 7. PRODUCT DETAILS
# ==========================================

@app.route("/product/<code>")
def product_details(code):

    connection = get_db()

    product = connection.execute("""
        SELECT * FROM products
        WHERE batch_code = ?
    """, (code,)).fetchone()

    events = connection.execute("""
        SELECT * FROM trace_events
        WHERE batch_code = ?
        ORDER BY id DESC
    """, (code,)).fetchall()

    connection.close()

    if product is None:
        abort(404)

    qr_filename = code + ".png"

    return render_template(
        "product.html",
        product=product,
        events=events,
        qr_filename=qr_filename
    )


# ==========================================
# 8. PUBLIC TRACEABILITY PAGE
# ==========================================

@app.route("/trace/<code>")
def trace_product(code):

    return product_details(code)


# ==========================================
# 9. ADD SUPPLY CHAIN EVENT
# ==========================================

@app.route("/product/<code>/events", methods=["POST"])
def add_event(code):

    event_type = request.form.get(
        "event_type", ""
    ).strip()

    if not event_type:

        flash("Please select an event type.", "error")

        return redirect(
            url_for("product_details", code=code)
        )

    connection = get_db()

    product = connection.execute("""
        SELECT batch_code FROM products
        WHERE batch_code = ?
    """, (code,)).fetchone()

    if product is None:
        connection.close()
        abort(404)

    connection.execute("""
        INSERT INTO trace_events (
            batch_code,
            event_type,
            location,
            description,
            updated_by,
            event_date
        )
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        code,
        event_type,
        request.form.get("location", ""),
        request.form.get("description", ""),
        request.form.get("updated_by", ""),
        datetime.now().isoformat(timespec="seconds")
    ))

    connection.commit()
    connection.close()

    flash("Supply-chain event added successfully.", "success")

    return redirect(
        url_for("product_details", code=code)
    )


# ==========================================
# 10. QR SCANNER PAGE
# ==========================================

@app.route("/scan")
def scan_page():

    return render_template("scan.html")


# ==========================================
# 11. PRODUCT JSON API
# ==========================================

@app.route("/api/products/<code>")
def product_api(code):

    connection = get_db()

    product = connection.execute("""
        SELECT * FROM products
        WHERE batch_code = ?
    """, (code,)).fetchone()

    events = connection.execute("""
        SELECT * FROM trace_events
        WHERE batch_code = ?
        ORDER BY id DESC
    """, (code,)).fetchall()

    connection.close()

    if product is None:

        return jsonify({
            "error": "Product not found"
        }), 404

    return jsonify({
        "product": dict(product),
        "events": [dict(event) for event in events]
    })


# ==========================================
# 12. 404 ERROR PAGE
# ==========================================

@app.errorhandler(404)
def page_not_found(error):

    return render_template("404.html"), 404


# ==========================================
# 13. RUN APPLICATION
# ==========================================

if __name__ == "__main__":

    initialize_database()

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )
