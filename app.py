import os
from datetime import datetime, timedelta

from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from authlib.integrations.flask_client import OAuth


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
    username = db.Column(db.String(120))
    email = db.Column(db.String(120), unique=True)
    password_hash = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    products = db.relationship("Product", backref="seller", lazy=True)


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    title = db.Column(db.String(200), nullable=False)
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
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)


class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_name = db.Column(db.String(120))
    payment_type = db.Column(db.String(100))
    amount = db.Column(db.String(50))
    note = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in {
        "png",
        "jpg",
        "jpeg",
        "gif",
        "webp",
    }


@app.route("/")
def index():
    products = Product.query.filter_by(is_active=True, is_rejected=False).order_by(
        Product.created_at.desc()
    ).all()

    return render_template(
        "index.html",
        products=products,
        categories=CATEGORIES,
        user_id=session.get("user_id"),
    )


@app.route("/register", methods=["GET", "POST"])
@app.route("/create-account", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username")
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
            username=username,
            email=email,
            password_hash=generate_password_hash(password),
        )

        db.session.add(user)
        db.session.commit()

        session["user_id"] = user.id
        session["user_email"] = user.email
        session["username"] = user.username

        return redirect(url_for("index"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")

        user = User.query.filter_by(email=email).first()

        if not user or not user.password_hash or not check_password_hash(
            user.password_hash, password
        ):
            flash("Wrong email/username or password")
            return redirect(url_for("login"))

        session["user_id"] = user.id