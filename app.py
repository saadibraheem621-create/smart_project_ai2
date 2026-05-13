import pandas as pd
import numpy as np
import os
from datetime import datetime, timedelta

from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from authlib.integrations.flask_client import OAuth
import replicate
import requests
import uuid
import pandas as pd
import numpy as np

app = Flask(__name__)

app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "zenvy-secret")
app.config["UPLOAD_FOLDER"] = "static/uploads"

db_url = os.environ.get("DATABASE_URL", "sqlite:///zenvy.db")
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)
oauth = OAuth(app)

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "12345")

google = oauth.register(
    name="google",
    client_id=os.environ.get("GOOGLE_CLIENT_ID"),
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

CATEGORIES = [
    "Mobiles",
    "Cars",
    "Electronics",
    "Real Estate",
    "Clothes",
    "Services",
    "Other",
]


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120))
    username = db.Column(db.String(120))
    email = db.Column(db.String(120), unique=True)
    password_hash = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    products = db.relationship("Product", backref="seller", lazy=True)


class DataAnalysisFile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(300))
    rows_count = db.Column(db.Integer)
    columns_count = db.Column(db.Integer)
    columns_names = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    title = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(100), default="Other")
    price = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text)
    image_name = db.Column(db.String(300))
    city = db.Column(db.String(100))

    is_active = db.Column(db.Boolean, default=True)
    is_rejected = db.Column(db.Boolean, default=False)

    # Ads
    is_featured = db.Column(db.Boolean, default=False)
    is_ad = db.Column(db.Boolean, default=False)
    ad_expire = db.Column(db.DateTime, nullable=True)
    featured_requested = db.Column(db.Boolean, default=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)


class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_name = db.Column(db.String(120))
    payment_type = db.Column(db.String(100))
    amount = db.Column(db.String(50))
    note = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


def current_user():
    if "user_id" not in session:
        return None
    return User.query.get(session["user_id"])


def generate_ai_image(prompt):

    output = replicate.run(
        "black-forest-labs/flux-schnell",
        input={
            "prompt": prompt
        }
    )

    image_url = output[0]

    return image_url


def generate_ai_product_image(title, description):
    prompt = f"""
    Professional marketplace product photo.
    Product: {title}.
    Description: {description}.
    Clean background, realistic, high quality.
    """

    output = replicate.run(
        "black-forest-labs/flux-schnell",
        input={
            "prompt": prompt,
            "num_outputs": 1,
            "aspect_ratio": "1:1",
            "output_format": "webp"
        }
    )

    image_url = output[0]

    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    filename = f"ai_{uuid.uuid4().hex}.webp"
    save_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)

    response = requests.get(image_url, timeout=60)
    response.raise_for_status()

    with open(save_path, "wb") as f:
        f.write(response.content)

    return filename


@app.context_processor
def inject_user():
    return {"user": current_user()}


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in [
        "png", "jpg", "jpeg", "gif", "webp"
    ]


def expire_old_ads():
    expired_ads = Product.query.filter(
        Product.is_ad == True,
        Product.ad_expire != None,
        Product.ad_expire < datetime.utcnow()
    ).all()

    for product in expired_ads:
        product.is_ad = False
        product.is_featured = False
        product.ad_expire = None

    if expired_ads:
        db.session.commit()
@app.route("/")
def home():
    return render_template("index.html")

@app.route("/data-analysis", methods=["GET", "POST"])
def data_analysis():

    if request.method == "GET":
        return render_template("data_analysis.html")

    file = request.files.get("csv_file")

    if not file:
        return "No file uploaded"

    if file.filename == "":
        return "Empty filename"

    os.makedirs("static/data_files", exist_ok=True)

    filename = secure_filename(file.filename)
    path = os.path.join("static/data_files", filename)

    file.save(path)

    try:
        df = pd.read_csv(path, encoding="utf-8")
    except:
        df = pd.read_csv(path, encoding="latin1")

    result = {
        "rows": df.shape[0],
        "columns": df.shape[1],
        "column_names": list(df.columns),
        "missing_values": df.isnull().sum().to_dict(),
        "sample": df.head(10).to_html(classes="table")
    }

    return render_template(
        "data_analysis.html",
        result=result
    )

@app.route("/add", methods=["GET", "POST"])
def add_product():
    if "user_id" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        title = request.form.get("title")
        category = request.form.get("category") or "Other"
        price = request.form.get("price")
        description = request.form.get("description")
        city = request.form.get("city")

        image_file = request.files.get("image")
        filename = ""

        if image_file and image_file.filename and allowed_file(image_file.filename):
            if os.path.isfile(app.config["UPLOAD_FOLDER"]):
                os.remove(app.config["UPLOAD_FOLDER"])

            os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

            filename = secure_filename(image_file.filename)
            save_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            image_file.save(save_path)

        generate_ai_image = request.form.get("generate_ai_image") == "on"

        if False and generate_ai_image and not filename and description:
            pass

        is_featured = request.form.get("is_featured") == "on"

        product = Product(
            title=title,
            category=category,
            price=price,
            description=description,
            image_name=filename,
            city=city,
            user_id=session["user_id"],
            is_featured=is_featured,
            is_ad=is_featured,
            is_active=True,
            is_rejected=False,
        )

        db.session.add(product)
        db.session.commit()

        flash("Product added successfully")
        return redirect(url_for("my_products"))

    return render_template("add_product.html", categories=CATEGORIES)


@app.route("/promote/<int:product_id>")
def promote_product(product_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    product = Product.query.get_or_404(product_id)

    if product.user_id != session["user_id"]:
        return redirect(url_for("my_products"))

    product.is_featured = True
    product.is_ad = True
    product.ad_expire = datetime.utcnow() + timedelta(days=7)
    product.featured_requested = False

    db.session.commit()

    flash("Your product is sponsored for 7 days")
    return redirect(url_for("my_products"))


@app.route("/my-products/delete/<int:product_id>")
def delete_product(product_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    product = Product.query.get_or_404(product_id)

    if product.user_id == session["user_id"]:
        db.session.delete(product)
        db.session.commit()

    return redirect(url_for("my_products"))


@app.route("/product/<int:product_id>")
def product_details(product_id):
    product = Product.query.get_or_404(product_id)
    return render_template("product.html", product=product)


@app.route("/edit-product/<int:product_id>", methods=["GET", "POST"])
def edit_product(product_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    product = Product.query.get_or_404(product_id)

    if product.user_id != session["user_id"]:
        return redirect(url_for("my_products"))

    if request.method == "POST":
        product.title = request.form.get("title")
        product.category = request.form.get("category") or "Other"
        product.price = request.form.get("price")
        product.description = request.form.get("description")
        product.city = request.form.get("city")

        image_file = request.files.get("image")

        if image_file and image_file.filename and allowed_file(image_file.filename):
            os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
            filename = secure_filename(image_file.filename)
            save_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            image_file.save(save_path)
            product.image_name = filename

        db.session.commit()

        flash("Product updated successfully")
        return redirect(url_for("my_products"))

    return render_template("edit_product.html", product=product, categories=CATEGORIES)


@app.route("/admin", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        password = request.form.get("password")

        if password == ADMIN_PASSWORD:
            session["admin"] = True
            return redirect(url_for("admin_dashboard"))

        flash("Wrong admin password")

    return render_template("admin_login.html")


@app.route("/admin/dashboard")
def admin_dashboard():
    if not session.get("admin"):
        return redirect(url_for("admin_login"))

    products = Product.query.order_by(Product.id.desc()).all()
    payments = Payment.query.order_by(Payment.id.desc()).all()

    return render_template("admin.html", products=products, payments=payments)


@app.route("/generate-image/<int:product_id>")
def generate_product_image(product_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    product = Product.query.get_or_404(product_id)

    if product.user_id != session["user_id"]:
        return redirect(url_for("my_products"))

    try:
        filename = generate_ai_product_image(
            product.title,
            product.description or product.title
        )

        product.image_name = filename
        db.session.commit()

        flash("AI image generated successfully")

    except Exception as e:
        print("AI IMAGE ERROR:", e)
        flash("AI image failed")

    return redirect(url_for("my_products"))


@app.route("/admin/approve-ad/<int:product_id>")
def approve_ad(product_id):
    if not session.get("admin"):
        return redirect(url_for("admin_login"))

    product = Product.query.get_or_404(product_id)

    product.is_featured = True
    product.is_ad = True
    product.ad_expire = datetime.utcnow() + timedelta(days=7)
    product.featured_requested = False

    db.session.commit()

    flash("Sponsored ad approved")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/remove-ad/<int:product_id>")
def remove_ad(product_id):
    if not session.get("admin"):
        return redirect(url_for("admin_login"))

    product = Product.query.get_or_404(product_id)

    product.is_featured = False
    product.is_ad = False
    product.ad_expire = None
    product.featured_requested = False

    db.session.commit()

    flash("Sponsored ad removed")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/approve/<int:product_id>")
def approve_product(product_id):
    if not session.get("admin"):
        return redirect(url_for("admin_login"))

    product = Product.query.get_or_404(product_id)
    product.is_active = True
    product.is_rejected = False

    db.session.commit()
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/reject/<int:product_id>")
def reject_product(product_id):
    if not session.get("admin"):
        return redirect(url_for("admin_login"))

    product = Product.query.get_or_404(product_id)
    product.is_active = False
    product.is_rejected = True

    db.session.commit()
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/delete/<int:product_id>")
def admin_delete_product(product_id):
    if not session.get("admin"):
        return redirect(url_for("admin_login"))

    product = Product.query.get_or_404(product_id)

    db.session.delete(product)
    db.session.commit()

    return redirect(url_for("admin_dashboard"))


@app.route("/payment", methods=["GET", "POST"])
def payment():
    if request.method == "POST":
        payment_record = Payment(
            user_name=request.form.get("user_name"),
            payment_type=request.form.get("payment_type"),
            amount=request.form.get("amount"),
            note=request.form.get("note"),
        )

        db.session.add(payment_record)
        db.session.commit()

        flash("Payment request sent")
        return redirect(url_for("home"))

    return render_template("payment.html")


@app.route("/init-db")
def init_db():
    db.create_all()
    return "Database initialized successfully"


@app.route("/fix-db")
def fix_db():
    db.create_all()

    db.session.execute(db.text("""
        ALTER TABLE product
        ADD COLUMN IF NOT EXISTS is_ad BOOLEAN DEFAULT FALSE;
    """))

    db.session.execute(db.text("""
        ALTER TABLE product
        ADD COLUMN IF NOT EXISTS ad_expire TIMESTAMP;
    """))

    db.session.execute(db.text("""
        ALTER TABLE product
        ADD COLUMN IF NOT EXISTS is_featured BOOLEAN DEFAULT FALSE;
    """))

    db.session.execute(db.text("""
        ALTER TABLE product
        ADD COLUMN IF NOT EXISTS featured_requested BOOLEAN DEFAULT FALSE;
    """))

    db.session.commit()

    return "Database fixed successfully"


with app.app_context():
    db.create_all()


@app.route("/my-products")
def my_products():

    if "user_id" not in session:
        return redirect(url_for("login"))

    products = Product.query.filter_by(
        user_id=session["user_id"]
    ).order_by(Product.id.desc()).all()

    return render_template(
        "my_products.html",
        products=products
    )


if __name__ == "__main__":
    app.run(debug=True)
