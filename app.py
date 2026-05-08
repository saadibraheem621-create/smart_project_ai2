from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from authlib.integrations.flask_client import OAuth
from datetime import datetime, timedelta
import os

app = Flask(__name__)

# =========================
# CONFIG
# =========================

app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "zenvy-secret")

app.config["UPLOAD_FOLDER"] = "static/uploads"

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "12345")

db_url = os.environ.get("DATABASE_URL", "sqlite:///zenvy.db")

if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# =========================
# GOOGLE LOGIN
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
# DATABASE MODEL
# =========================

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    title = db.Column(db.String(200), nullable=False)

    description = db.Column(db.Text, nullable=False)

    price = db.Column(db.Float, nullable=False)

    image = db.Column(db.String(300))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# =========================
# HOME
# =========================

@app.route("/login")
def login():
    pass


@app.route("/")
def home():

    q = request.args.get("q", "")
    selected_category = request.args.get("category", "")

    query = Product.query

    if q:
        query = query.filter(Product.title.ilike(f"%{q}%"))

    if selected_category:
        query = query.filter_by(category=selected_category)

    products = query.order_by(Product.id.desc()).all()

    categories = [
        "Cars",
        "Phones",
        "Electronics",
        "Clothes",
        "Home",
        "Other"
    ]

    user = None

    return render_template(
        "index.html",
        products=products,
        q=q,
        categories=categories,
        selected_category=selected_category,
        user=user
    )


@app.route("/add")
def add():
    pass

# =========================
# ADD PRODUCT
# =========================

@app.route("/add", methods=["GET", "POST"])
def add_product():

    if session.get("admin") != True:
        return redirect(url_for("admin_login"))

    if request.method == "POST":

        title = request.form.get("title")

        description = request.form.get("description")

        price = request.form.get("price")

        image_file = request.files.get("image")

        filename = ""

        if image_file and image_file.filename != "":

            filename = secure_filename(image_file.filename)

            save_path = os.path.join(
                app.config["UPLOAD_FOLDER"],
                filename
            )

            os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

            image_file.save(save_path)

        product = Product(
            title=title,
            description=description,
            price=float(price),
            image=filename
        )

        db.session.add(product)

        db.session.commit()

        flash("Product added successfully")

        return redirect(url_for("home"))

    return render_template("add_product.html")

# =========================
# EDIT PRODUCT
# =========================

@app.route("/edit/<int:id>", methods=["GET", "POST"])
def edit_product(id):

    if session.get("admin") != True:
        return redirect(url_for("admin_login"))

    product = Product.query.get_or_404(id)

    if request.method == "POST":

        product.title = request.form.get("title")

        product.description = request.form.get("description")

        product.price = float(request.form.get("price"))

        image_file = request.files.get("image")

        if image_file and image_file.filename != "":

            filename = secure_filename(image_file.filename)

            save_path = os.path.join(
                app.config["UPLOAD_FOLDER"],
                filename
            )

            image_file.save(save_path)

            product.image = filename

        db.session.commit()

        flash("Updated successfully")

        return redirect(url_for("home"))

    return render_template(
        "edit_product.html",
        product=product
    )

# =========================
# DELETE PRODUCT
# =========================

@app.route("/delete/<int:id>")
def delete_product(id):

    if session.get("admin") != True:
        return redirect(url_for("admin_login"))

    product = Product.query.get_or_404(id)

    db.session.delete(product)

    db.session.commit()

    flash("Deleted successfully")

    return redirect(url_for("home"))

# =========================
# ADMIN LOGIN
# =========================

@app.route("/admin", methods=["GET", "POST"])
def admin_login():

    if request.method == "POST":

        password = request.form.get("password")

        if password == ADMIN_PASSWORD:

            session["admin"] = True

            return redirect(url_for("add_product"))

        flash("Wrong password")

    return render_template("admin.html")

# =========================
# LOGOUT
# =========================

@app.route("/logout")
def logout():

    session.clear()

    return redirect(url_for("home"))

# =========================
# GOOGLE LOGIN
# =========================

@app.route("/login/google")
def google_login():

    redirect_uri = url_for(
        "google_callback",
        _external=True
    )

    return google.authorize_redirect(redirect_uri)

@app.route("/callback")
def google_callback():

    token = google.authorize_access_token()

    user = token.get("userinfo")

    session["user"] = user

    return redirect(url_for("home"))

# =========================
# CREATE DB
# =========================

with app.app_context():
    db.create_all()

# =========================
# RUN
# =========================

if __name__ == "__main__":
    app.run(debug=True)