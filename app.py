from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from datetime import datetime
import os

app = Flask(__name__)

app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-this-secret")
app.config["UPLOAD_FOLDER"] = "static/uploads"

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "12345")

db_url = os.environ.get("DATABASE_URL", "sqlite:///market.db")
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    seller_name = db.Column(db.String(100), nullable=False)
    whatsapp = db.Column(db.String(50), nullable=False)
    title = db.Column(db.String(150), nullable=False)
    category = db.Column(db.String(100), nullable=False)
    price = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text)
    image_name = db.Column(db.String(200))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


CATEGORIES = [
    "موبايلات",
    "سيارات",
    "أجهزة",
    "أثاث",
    "ملابس",
    "عقارات",
    "خدمات",
    "أخرى"
]


@app.route("/")
def index():
    q = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()

    query = Product.query.filter_by(is_active=True)

    if q:
        query = query.filter(Product.title.contains(q))

    if category:
        query = query.filter_by(category=category)

    products = query.order_by(Product.created_at.desc()).all()

    return render_template(
        "index.html",
        products=products,
        categories=CATEGORIES,
        q=q,
        selected_category=category
    )


@app.route("/add", methods=["GET", "POST"])
def add_product():
    if request.method == "POST":
        seller_name = request.form.get("seller_name")
        whatsapp = request.form.get("whatsapp")
        title = request.form.get("title")
        category = request.form.get("category")
        price = request.form.get("price")
        description = request.form.get("description")

        image = request.files.get("image")
        image_name = None

        if image and image.filename:
            os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
            image_name = secure_filename(image.filename)
            image.save(os.path.join(app.config["UPLOAD_FOLDER"], image_name))

        product = Product(
            seller_name=seller_name,
            whatsapp=whatsapp,
            title=title,
            category=category,
            price=price,
            description=description,
            image_name=image_name,
            is_active=True
        )

        db.session.add(product)
        db.session.commit()

        flash("تم نشر المنتج بنجاح")
        return redirect(url_for("index"))

    return render_template("add_product.html", categories=CATEGORIES)


@app.route("/product/<int:product_id>")
def product_details(product_id):
    product = Product.query.get_or_404(product_id)
    return render_template("product.html", product=product)


@app.route("/admin-login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        password = request.form.get("password")

        if password == ADMIN_PASSWORD:
            session["admin"] = True
            return redirect(url_for("admin"))
        else:
            flash("كلمة السر غير صحيحة")

    return render_template("admin_login.html")


@app.route("/admin")
def admin():
    if not session.get("admin"):
        return redirect(url_for("admin_login"))

    products = Product.query.order_by(Product.created_at.desc()).all()
    return render_template("admin.html", products=products)


@app.route("/hide/<int:product_id>")
def hide_product(product_id):
    if not session.get("admin"):
        return redirect(url_for("admin_login"))

    product = Product.query.get_or_404(product_id)
    product.is_active = False
    db.session.commit()
    return redirect(url_for("admin"))


@app.route("/show/<int:product_id>")
def show_product(product_id):
    if not session.get("admin"):
        return redirect(url_for("admin_login"))

    product = Product.query.get_or_404(product_id)
    product.is_active = True
    db.session.commit()
    return redirect(url_for("admin"))


@app.route("/delete/<int:product_id>")
def delete_product(product_id):
    if not session.get("admin"):
        return redirect(url_for("admin_login"))

    product = Product.query.get_or_404(product_id)

    if product.image_name:
        image_path = os.path.join(app.config["UPLOAD_FOLDER"], product.image_name)
        if os.path.exists(image_path):
            os.remove(image_path)

    db.session.delete(product)
    db.session.commit()
    return redirect(url_for("admin"))


@app.route("/logout")
def logout():
    session.pop("admin", None)
    return redirect(url_for("index"))


with app.app_context():
    db.create_all()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)