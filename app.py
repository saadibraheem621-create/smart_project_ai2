from flask import Flask, render_template, request, redirect, url_for, session, flash
from authlib.integrations.flask_client import OAuth
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
import os

app = Flask(__name__)

# =========================
# CONFIG
# =========================

app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "zenvy-secret")
app.config["UPLOAD_FOLDER"] = "static/uploads"

db_url = os.environ.get("DATABASE_URL", "sqlite:///zenvy.db")

if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# =========================
# GOOGLE OAUTH
# =========================

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

# =========================
# MODELS
# =========================

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    full_name = db.Column(db.String(200))
    username = db.Column(db.String(100), unique=True)
    whatsapp = db.Column(db.String(100))

    email = db.Column(db.String(200), unique=True)
    password_hash = db.Column(db.String(500))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# =========================
# HOME
# =========================

@app.route("/")
def index():
    return render_template("index.html")


# =========================
# REGISTER
# =========================

@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        full_name = request.form.get("full_name")
        username = request.form.get("username")
        whatsapp = request.form.get("whatsapp")
        email = request.form.get("email")
        password = request.form.get("password")

        existing_user = User.query.filter(
            (User.email == email) |
            (User.username == username)
        ).first()

        if existing_user:
            flash("User already exists")
            return redirect(url_for("register"))

        hashed_password = generate_password_hash(password)

        user = User(
            full_name=full_name,
            username=username,
            whatsapp=whatsapp,
            email=email,
            password_hash=hashed_password
        )

        db.session.add(user)
        db.session.commit()

        flash("Account created successfully")
        return redirect(url_for("login"))

    return render_template("register.html")


# =========================
# LOGIN
# =========================

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        email_or_username = request.form.get("email")
        password = request.form.get("password")

        user = User.query.filter(
            (User.email == email_or_username) |
            (User.username == email_or_username)
        ).first()

        if user and check_password_hash(user.password_hash, password):

            session["user_id"] = user.id
            session["username"] = user.username

            flash("Login successful")
            return redirect(url_for("index"))

        flash("Wrong email/username or password")
        return redirect(url_for("login"))

    return render_template("login.html")


# =========================
# GOOGLE LOGIN
# =========================

@app.route("/google-login")
def google_login():

    redirect_uri = "https://smartprojectai2-production-4709.up.railway.app/auth/google/callback"

    return google.authorize_redirect(redirect_uri)


@app.route("/auth/google/callback")
def google_callback():

    token = google.authorize_access_token()

    resp = google.get("https://www.googleapis.com/oauth2/v3/userinfo")

    user_info = resp.json()

    email = user_info.get("email")
    name = user_info.get("name", "Google User")

    if not email:
        flash("Google login failed")
        return redirect(url_for("login"))

    user = User.query.filter_by(email=email).first()

    if not user:

        username = email.split("@")[0]

        existing_username = User.query.filter_by(username=username).first()

        if existing_username:
            username = username + str(int(datetime.utcnow().timestamp()))

        
        user = User(
    username=username,
    
    email=email,
    password_hash=generate_password_hash(os.urandom(16).hex())
)

        db.session.add(user)
        db.session.commit()

    session["user_id"] = user.id
    session["username"] = user.username

    flash("Logged in with Google successfully")

    return redirect(url_for("index"))


# =========================
# LOGOUT
# =========================

@app.route("/logout")
def logout():

    session.clear()

    flash("Logged out successfully")

    return redirect(url_for("login"))


# =========================
# CREATE DATABASE
# =========================

with app.app_context():
    db.create_all()


# =========================
# RUN
# =========================

if __name__ == "__main__":
    app.run(debug=True)