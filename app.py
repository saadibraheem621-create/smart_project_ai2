import os
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from authlib.integrations.flask_client import OAuth
from datetime import datetime, timedelta

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


@app.context_processor
def inject_user():
    return {"user": current_user()}


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in [
        "png",
        "jpg",
        "jpeg",
        "gif",
        "webp",
    ]


@app.route("/")
def home():
    q = request.args.get("q", "")
    selected_category = request.args.get("category", "")

    query = Product.query.filter_by(is_active=True, is_rejected=False)

    if q:
        query = query.filter(Product.title.ilike(f"%{q}%"))

    if selected_category:
        query = query.filter_by(category=selected_category)

    products = query.order_by(Product.id.desc()).all()

    return render_template(
        "index.html",
        products=products,
        categories=CATEGORIES,
        selected_category=selected_category,
        q=q,
    )


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        full_name = request.form.get(
            "full_name") or request.form.get("username")
        email = request.form.get("email")
        password = request.form.get("password")

        if not email or not password:
            flash("Please fill all fields")
            return redirect(url_for("register"))

        old_user = User.query.filter_by(email=email).first()

        if old_user:
            flash("Email already exists")
            return redirect(url_for("login"))

        user = User(
            full_name=full_name,
            username=full_name,
            email=email,
            password_hash=generate_password_hash(password),
        )

        db.session.add(user)
        db.session.commit()

        session["user_id"] = user.id
        session["user_email"] = user.email

        return redirect(url_for("home"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")

        user = User.query.filter_by(email=email).first()

        if not user or not user.password_hash or not check_password_hash(user.password_hash, password):
            flash("Wrong email or password")
            return redirect(url_for("login"))

        session["user_id"] = user.id
        session["user_email"] = user.email

        return redirect(url_for("home"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


@app.route("/google-login")
def google_login():
    redirect_uri = url_for(
        "google_callback",
        _external=True,
        _scheme="https"
    )

    return google.authorize_redirect(redirect_uri)


@app.route("/auth/google/callback")
def google_callback():
    token = google.authorize_access_token()
    user_info = token.get("userinfo")

    if not user_info:
        resp = google.get("https://www.googleapis.com/oauth2/v3/userinfo")
        user_info = resp.json()

    email = user_info.get("email")
    name = user_info.get("name") or email

    if not email:
        flash("Google login failed")
        return redirect(url_for("login"))

    user = User.query.filter_by(email=email).first()

    if not user:
        user = User(
            full_name=name,
            username=name,
            email=email,
            password_hash=generate_password_hash(os.urandom(16).hex()),
        )

        db.session.add(user)
        db.session.commit()

    session["user_id"] = user.id
    session["user_email"] = user.email

    return redirect(url_for("home"))


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
            os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

            filename = secure_filename(image_file.filename)

            save_path = os.path.join(
                app.config["UPLOAD_FOLDER"],
                filename
            )

            image_file.save(save_path)

        product = Product(
            title=title,
            category=category,
            price=price,
            description=description,
            image_name=filename,
            city=city,
            user_id=session["user_id"],
            is_active=True,
            is_rejected=False,
        )

        db.session.add(product)
        db.session.commit()

        flash("Product added successfully")

        return redirect(url_for("my_products"))

    return render_template(
        "add_product.html",
        categories=CATEGORIES
    )


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

    return render_template(
        "product.html",
        product=product
    )


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

            save_path = os.path.join(
                app.config["UPLOAD_FOLDER"],
                filename
            )

            image_file.save(save_path)

            product.image_name = filename

        db.session.commit()

        flash("Product updated successfully")

        return redirect(url_for("my_products"))

    return render_template(
        "edit_product.html",
        product=product,
        categories=CATEGORIES
    )


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

    return render_template(
        "admin.html",
        products=products,
        payments=payments
    )


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


@app.route("/promote/<int:product_id>")
def promote_product(product_id):

    if "user_id" not in session:
        return redirect(url_for("login"))

    product = Product.query.get_or_404(product_id)

    if product.user_id != session["user_id"]:
        return redirect(url_for("my_products"))

    # تفعيل الإعلان لمدة 7 أيام
    product.is_ad = True
    product.ad_expire = datetime.utcnow() + timedelta(days=7)

    db.session.commit()

    flash("Your ad is now featured for 7 days")

    return redirect(url_for("my_products"))


@app.route("/init-db")
def init_db():
    db.create_all()

    return "Database initialized successfully"


with app.app_context():
    db.create_all()


if __name__ == "__main__":
    app.run(debug=True)
