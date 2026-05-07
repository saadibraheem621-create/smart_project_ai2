from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import os

app = Flask(__name__)

app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "zenvy-secret")
app.config["UPLOAD_FOLDER"] = "static/uploads"
app.config["PAYMENT_PROOF_FOLDER"] = "static/payment_proofs"

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "12345")

ZAIN_CASH_NUMBER = os.environ.get("ZAIN_CASH_NUMBER", "07739046052")
USDT_WALLET = os.environ.get("USDT_WALLET", "TTDgpsoLSry46z2cXaiXd9uxN8vj8pL3ov")
MASTERCARD_LINK = os.environ.get("MASTERCARD_LINK", "")

db_url = os.environ.get("DATABASE_URL", "sqlite:///zenvy.db")
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

CATEGORIES = [
    "Mobiles", "Cars", "Electronics", "Furniture",
    "Fashion", "Real Estate", "Services", "Other"
]


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    username = db.Column(db.String(80), unique=True, nullable=False)
    whatsapp = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    is_pro = db.Column(db.Boolean, default=False)
    pro_until = db.Column(db.DateTime)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    products = db.relationship("Product", backref="seller", lazy=True)


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    category = db.Column(db.String(100), nullable=False)
    price = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text)
    image_name = db.Column(db.String(200))
    city = db.Column(db.String(100))

    is_active = db.Column(db.Boolean, default=False)
    is_rejected = db.Column(db.Boolean, default=False)

     is_featured = db.Column(db.Boolean, default=False)
    featured_until = db.Column(db.DateTime)
    featured_requested = db.Column(db.Boolean, default=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)


class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=True)

    service_type = db.Column(db.String(50), nullable=False)  # featured / pro
    method = db.Column(db.String(50), nullable=False)        # zain / usdt / mastercard
    amount = db.Column(db.String(50), nullable=False)

    payer_phone = db.Column(db.String(50))
    transaction_note = db.Column(db.String(250))
    proof_image = db.Column(db.String(250))

    status = db.Column(db.String(50), default="pending")     # pending / approved / rejected
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", backref="payments")
    product = db.relationship("Product", backref="payments")


def current_user():
    user_id = session.get("user_id")
    if user_id:
        return User.query.get(user_id)
    return None


def is_user_pro(user):
    if not user:
        return False

    if user.is_pro and user.pro_until and user.pro_until > datetime.utcnow():
        return True

    return False


def save_file(file, folder):
    if file and file.filename:
        os.makedirs(folder, exist_ok=True)
        filename = secure_filename(file.filename)
        file.save(os.path.join(folder, filename))
        return filename
    return None


@app.route("/")
def index():
    q = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    now = datetime.utcnow()

    featured_products = Product.query.filter(
        Product.is_active == True,
        Product.is_featured == True,
        Product.featured_until > now
    ).order_by(Product.featured_until.desc()).all()

    query = Product.query.filter_by(is_active=True)

    if q:
        query = query.filter(Product.title.contains(q))

    if category:
        query = query.filter_by(category=category)

    products = query.order_by(Product.created_at.desc()).all()

    return render_template(
        "index.html",
        products=products,
        featured_products=featured_products,
        categories=CATEGORIES,
        q=q,
        selected_category=category,
        user=current_user()
    )


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        full_name = request.form.get("full_name")
        username = request.form.get("username")
        whatsapp = request.form.get("whatsapp")
        email = request.form.get("email")
        password = request.form.get("password")

        if User.query.filter_by(email=email).first():
            flash("Email already registered")
            return redirect(url_for("register"))

        if User.query.filter_by(username=username).first():
            flash("Username already registered")
            return redirect(url_for("register"))

        user = User(
            full_name=full_name,
            username=username,
            whatsapp=whatsapp,
            email=email,
            password_hash=generate_password_hash(password)
        )

        db.session.add(user)
        db.session.commit()

        session["user_id"] = user.id
        return redirect(url_for("index"))

    return render_template("register.html", user=current_user())


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        login_input = request.form.get("email")
        password = request.form.get("password")

        user = User.query.filter(
            (User.email == login_input) | (User.username == login_input)
        ).first()

        if not user or not check_password_hash(user.password_hash, password):
            flash("Wrong email/username or password")
            return redirect(url_for("login"))

        session["user_id"] = user.id
        return redirect(url_for("index"))

    return render_template("login.html", user=current_user())


@app.route("/logout")
def logout():
    session.pop("user_id", None)
    session.pop("admin", None)
    return redirect(url_for("index"))
    @app.route("/admin/approve-product/<int:product_id>")
def approve_product(product_id):
    if not session.get("admin"):
        return redirect(url_for("admin_login"))

    product = Product.query.get_or_404(product_id)
    product.is_active = True
    product.is_rejected = False

    db.session.commit()
    flash("Product approved")
    return redirect(url_for("admin"))


@app.route("/admin/reject-product/<int:product_id>")
def reject_product(product_id):
    if not session.get("admin"):
        return redirect(url_for("admin_login"))

    product = Product.query.get_or_404(product_id)
    product.is_active = False
    product.is_rejected = True

    db.session.commit()
    flash("Product rejected")
    return redirect(url_for("admin"))


@app.route("/add", methods=["GET", "POST"])
def add_product():
    user = current_user()
    if not user:
        return redirect(url_for("login"))

    if request.method == "POST":
        user_products_count = Product.query.filter_by(user_id=user.id).count()

        if not is_user_pro(user) and user_products_count >= 3:
            flash("Free sellers can add 3 products only. Upgrade to Pro.")
            return redirect(url_for("upgrade_pro"))

        image = request.files.get("image")
        image_name = save_file(image, app.config["UPLOAD_FOLDER"])

        product = Product(
            title=request.form.get("title"),
            category=request.form.get("category"),
            price=request.form.get("price"),
            city=request.form.get("city"),
            description=request.form.get("description"),
            image_name=image_name,
            user_id=user.id
        )

        db.session.add(product)
        db.session.commit()

        return redirect(url_for("my_products"))

    return render_template("add_product.html", categories=CATEGORIES, user=user)


@app.route("/product/<int:product_id>")
def product_details(product_id):
    product = Product.query.get_or_404(product_id)
    return render_template("product.html", product=product, user=current_user())


@app.route("/my-products")
def my_products():
    user = current_user()
    if not user:
        return redirect(url_for("login"))

    products = Product.query.filter_by(user_id=user.id).order_by(Product.created_at.desc()).all()
    return render_template("my_products.html", products=products, user=user, is_pro=is_user_pro(user))


@app.route("/my-products/delete/<int:product_id>")
def delete_my_product(product_id):
    user = current_user()
    if not user:
        return redirect(url_for("login"))

    product = Product.query.get_or_404(product_id)

    if product.user_id != user.id:
        return redirect(url_for("my_products"))

    db.session.delete(product)
    db.session.commit()

    return redirect(url_for("my_products"))


@app.route("/my-products/hide/<int:product_id>")
def hide_my_product(product_id):
    user = current_user()
    if not user:
        return redirect(url_for("login"))

    product = Product.query.get_or_404(product_id)

    if product.user_id == user.id:
        product.is_active = False
        db.session.commit()

    return redirect(url_for("my_products"))


@app.route("/my-products/show/<int:product_id>")
def show_my_product(product_id):
    user = current_user()
    if not user:
        return redirect(url_for("login"))

    product = Product.query.get_or_404(product_id)

    if product.user_id == user.id:
        product.is_active = True
        db.session.commit()

    return redirect(url_for("my_products"))


@app.route("/payment/featured/<int:product_id>", methods=["GET", "POST"])
def payment_featured(product_id):
    user = current_user()
    if not user:
        return redirect(url_for("login"))

    product = Product.query.get_or_404(product_id)

    if product.user_id != user.id:
        return redirect(url_for("my_products"))

    if request.method == "POST":
        proof = request.files.get("proof")
        proof_image = save_file(proof, app.config["PAYMENT_PROOF_FOLDER"])

        payment = Payment(
            user_id=user.id,
            product_id=product.id,
            service_type="featured",
            method=request.form.get("method"),
            amount="5 USD",
            payer_phone=request.form.get("payer_phone"),
            transaction_note=request.form.get("transaction_note"),
            proof_image=proof_image,
            status="pending"
        )

        product.featured_requested = True

        db.session.add(payment)
        db.session.commit()

        flash("Payment request sent. Admin will review it.")
        return redirect(url_for("my_products"))

    return render_template(
        "payment.html",
        user=user,
        product=product,
        service_type="featured",
        amount="5 USD",
        zain_cash=ZAIN_CASH_NUMBER,
        usdt_wallet=USDT_WALLET,
        mastercard_link=MASTERCARD_LINK
    )


@app.route("/my-products/edit/<int:product_id>", methods=["GET", "POST"])
def edit_my_product(product_id):
    user = current_user()
    if not user:
        return redirect(url_for("login"))

    product = Product.query.get_or_404(product_id)

    if product.user_id != user.id:
        return redirect(url_for("my_products"))

    if request.method == "POST":
        product.title = request.form.get("title")
        product.category = request.form.get("category")
        product.price = request.form.get("price")
        product.city = request.form.get("city")
        product.description = request.form.get("description")

        image = request.files.get("image")
        if image and image.filename:
            image_name = save_file(image, app.config["UPLOAD_FOLDER"])
            product.image_name = image_name

        db.session.commit()
        flash("Product updated successfully")
        return redirect(url_for("my_products"))

    return render_template(
        "edit_product.html",
        product=product,
        categories=CATEGORIES,
        user=user
    )


@app.route("/admin-login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        password = request.form.get("password")

        if password == ADMIN_PASSWORD:
            session["admin"] = True
            return redirect(url_for("admin"))

        flash("Wrong admin password")

    return render_template("admin_login.html", user=current_user())


@app.route("/admin")
def admin():
    if not session.get("admin"):
        return redirect(url_for("admin_login"))

    products = Product.query.order_by(Product.created_at.desc()).all()
    users = User.query.order_by(User.created_at.desc()).all()
    payments = Payment.query.order_by(Payment.created_at.desc()).all()

    return render_template(
        "admin.html",
        products=products,
        users=users,
        payments=payments,
        user=current_user()
    )


@app.route("/admin/delete-product/<int:product_id>")
def admin_delete_product(product_id):
    if not session.get("admin"):
        return redirect(url_for("admin_login"))

    product = Product.query.get_or_404(product_id)
    db.session.delete(product)
    db.session.commit()

    return redirect(url_for("admin"))


@app.route("/admin/approve-payment/<int:payment_id>")
def approve_payment(payment_id):
    if not session.get("admin"):
        return redirect(url_for("admin_login"))

    payment = Payment.query.get_or_404(payment_id)
    payment.status = "approved"

    if payment.service_type == "featured" and payment.product:
        payment.product.is_featured = True
        payment.product.featured_requested = False
        payment.product.featured_until = datetime.utcnow() + timedelta(days=7)

    if payment.service_type == "pro":
        user = User.query.get(payment.user_id)
        user.is_pro = True
        user.pro_until = datetime.utcnow() + timedelta(days=30)

    db.session.commit()
    return redirect(url_for("admin"))


@app.route("/admin/reject-payment/<int:payment_id>")
def reject_payment(payment_id):
    if not session.get("admin"):
        return redirect(url_for("admin_login"))

    payment = Payment.query.get_or_404(payment_id)
    payment.status = "rejected"

    if payment.product:
        payment.product.featured_requested = False

    db.session.commit()
    return redirect(url_for("admin"))


with app.app_context():
    db.create_all()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)