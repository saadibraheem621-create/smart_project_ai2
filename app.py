from flask import Flask, render_template, request, redirect, url_for, session, flash
from authlib.integrations.flask_client import OAuth
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
import os

app = Flask(__name__)

app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "zenvy-secret")
app.config["UPLOAD_FOLDER"] = "static/uploads"

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "12345")

db_url = os.environ.get("DATABASE_URL", "sqlite:///zenvy.db")
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)
oauth = OAuth(app)

google = oauth.register(
    name="google",
    client_id=os.environ.get("GOOGLE_CLIENT_ID"),
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={
        "scope": "openid email profile"
    }
)
@app.route("/google-login")
def google_login():
    redirect_uri = url_for("redirect_uri = "https://smartprojectai2-production-4709.up.railway.app/auth/google/callback"", _external=True)
    return google.authorize_redirect(redirect_uri)


@app.route("/auth/google/callback")
def google_callback():
    token = google.authorize_access_token()
    user_info = token.get("userinfo")

    email = user_info.get("email")
    name = user_info.get("name")

    user = User.query.filter_by(email=email).first()

    if not user:
        username = email.split("@")[0]

        existing_username = User.query.filter_by(username=username).first()
        if existing_username:
            username = username + str(int(datetime.utcnow().timestamp()))

        user = User(
            full_name=name,
            username=username,
            whatsapp="google-login",
            email=email,
            password_hash=generate_password_hash(os.urandom(16).hex())
        )

        db.session.add(user)
        db.session.commit()

    session["user_id"] = user.id

    return redirect(url_for("index"))

CATEGORIES = [
    "Mobiles",
    "Cars",
    "Electronics",
    "Furniture",
    "Fashion",
    "Real Estate",
    "Services",
    "Other"
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

    user_name = db.Column(db.String(120))
    payment_type = db.Column(db.String(100))
    amount = db.Column(db.String(50))
    note = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)


def current_user():
    user_id = session.get("user_id")
    if user_id:
        return User.query.get(user_id)
    return None


@app.route("/")
def index():
    q = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()

    query = Product.query.filter_by(is_active=True, is_rejected=False)

    if q:
        query = query.filter(Product.title.contains(q))

    if category:
        query = query.filter_by(category=category)

    products = query.order_by(
        Product.is_featured.desc(),
        Product.created_at.desc()
    ).all()

    return render_template(
        "index.html",
        products=products,
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
        flash("Account created successfully")

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
@app.route("/forgot-password")
def forgot_password():
    return render_template("forgot_password.html")


@app.route("/logout")
def logout():
    session.pop("user_id", None)
    session.pop("admin", None)
    return redirect(url_for("index"))


@app.route("/add", methods=["GET", "POST"])
def add_product():
    user = current_user()

    if not user:
        return redirect(url_for("login"))

    if request.method == "POST":
        title = request.form.get("title")
        category = request.form.get("category")
        price = request.form.get("price")
        city = request.form.get("city")
        description = request.form.get("description")

        image = request.files.get("image")
        image_name = None

        if image and image.filename:
            os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
            image_name = secure_filename(image.filename)
            image.save(os.path.join(app.config["UPLOAD_FOLDER"], image_name))

        product = Product(
            title=title,
            category=category,
            price=price,
            city=city,
            description=description,
            image_name=image_name,
            user_id=user.id,
            is_active=False,
            is_rejected=False
        )

        db.session.add(product)
        db.session.commit()

        flash("Product submitted for review")
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

    products = Product.query.filter_by(user_id=user.id).order_by(
        Product.created_at.desc()
    ).all()

    return render_template("my_products.html", products=products, user=user)


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

    flash("Product deleted")
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
        product.is_rejected = False
        db.session.commit()

    return redirect(url_for("my_products"))


@app.route("/my-products/edit/<int:product_id>", methods=["GET", "POST"])
def edit_product(product_id):
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
            os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
            image_name = secure_filename(image.filename)
            image.save(os.path.join(app.config["UPLOAD_FOLDER"], image_name))
            product.image_name = image_name

        product.is_active = False
        product.is_rejected = False

        db.session.commit()

        flash("Product updated and sent for review")
        return redirect(url_for("my_products"))

    return render_template(
        "edit_product.html",
        product=product,
        categories=CATEGORIES,
        user=user
    )


@app.route("/request-featured/<int:product_id>")
def request_featured(product_id):
    user = current_user()

    if not user:
        return redirect(url_for("login"))

    product = Product.query.get_or_404(product_id)

    if product.user_id != user.id:
        return redirect(url_for("my_products"))

    product.featured_requested = True
    db.session.commit()

    flash("Featured ad request sent")
    return redirect(url_for("my_products"))


@app.route("/payment", methods=["GET", "POST"])
def payment():
    user = current_user()

    if request.method == "POST":
        user_name = request.form.get("user_name")
        payment_type = request.form.get("payment_type")
        amount = request.form.get("amount")
        note = request.form.get("note")

        pay = Payment(
            user_name=user_name,
            payment_type=payment_type,
            amount=amount,
            note=note
        )

        db.session.add(pay)
        db.session.commit()

        flash("Payment request sent")
        return redirect(url_for("index"))

    return render_template("payment.html", user=user)


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

    users = User.query.order_by(User.created_at.desc()).all()
    products = Product.query.order_by(Product.created_at.desc()).all()
    payments = Payment.query.order_by(Payment.created_at.desc()).all()

    total_users = User.query.count()
    total_products = Product.query.count()
    pending_products = Product.query.filter_by(is_active=False, is_rejected=False).count()
    approved_products = Product.query.filter_by(is_active=True).count()
    rejected_products = Product.query.filter_by(is_rejected=True).count()
    featured_requests = Product.query.filter_by(featured_requested=True).count()

    return render_template(
        "admin.html",
        users=users,
        products=products,
        payments=payments,
        total_users=total_users,
        total_products=total_products,
        pending_products=pending_products,
        approved_products=approved_products,
        rejected_products=rejected_products,
        featured_requests=featured_requests,
        user=current_user()
    )


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


@app.route("/admin/delete-product/<int:product_id>")
def admin_delete_product(product_id):
    if not session.get("admin"):
        return redirect(url_for("admin_login"))

    product = Product.query.get_or_404(product_id)

    db.session.delete(product)
    db.session.commit()

    flash("Product deleted")
    return redirect(url_for("admin"))


@app.route("/admin/feature-product/<int:product_id>")
def feature_product(product_id):
    if not session.get("admin"):
        return redirect(url_for("admin_login"))

    product = Product.query.get_or_404(product_id)

    product.is_featured = True
    product.featured_requested = False
    product.featured_until = datetime.utcnow() + timedelta(days=30)

    db.session.commit()

    flash("Product featured")
    return redirect(url_for("admin"))


@app.route("/admin/remove-featured/<int:product_id>")
def remove_featured(product_id):
    if not session.get("admin"):
        return redirect(url_for("admin_login"))

    product = Product.query.get_or_404(product_id)

    product.is_featured = False
    product.featured_until = None

    db.session.commit()

    flash("Featured removed")
    return redirect(url_for("admin"))


@app.route("/admin/delete-payment/<int:payment_id>")
def delete_payment(payment_id):
    if not session.get("admin"):
        return redirect(url_for("admin_login"))

    payment_item = Payment.query.get_or_404(payment_id)

    db.session.delete(payment_item)
    db.session.commit()

    flash("Payment request deleted")
    return redirect(url_for("admin"))


with app.app_context():
    db.create_all()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)