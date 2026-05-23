import pandas as pd
import numpy as np
import os
from datetime import datetime, timedelta
import uuid
import html
from werkzeug.utils import secure_filename

from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from authlib.integrations.flask_client import OAuth
import replicate
import requests
from sqlalchemy import text
from functools import wraps

app = Flask(__name__)

# Configuration
PLAN_LIMITS = {
    "basic": {
        "max_mb": 20,
        "ml": False,
        "pdf": False,
    },
    "pro": {
        "max_mb": 100,
        "ml": True,
        "pdf": True,
    },
    "business": {
        "max_mb": 500,
        "ml": True,
        "pdf": True,
    }
}

app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "zenvy-secret-key-change-in-production")
app.config["UPLOAD_FOLDER"] = "static/uploads"
app.config["BOOK_UPLOAD_FOLDER"] = "uploads/books"

# Database configuration
db_url = os.environ.get("DATABASE_URL", "sqlite:///zenvy.db")
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)
oauth = OAuth(app)

# Admin password
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "12345")

# Google OAuth
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

# Database Models
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120))
    username = db.Column(db.String(120))
    email = db.Column(db.String(120), unique=True)
    password_hash = db.Column(db.String(255))
    credits = db.Column(db.Integer, default=3)
    plan = db.Column(db.String(50), default="free")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    products = db.relationship("Product", backref="seller", lazy=True)

class AnalysisJob(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer)
    plan = db.Column(db.String(50))
    filename = db.Column(db.String(255))
    status = db.Column(db.String(50), default="pending")
    result_json = db.Column(db.Text)
    report_pdf = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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

# Helper Functions
def current_user():
    if "user_id" not in session:
        return None
    return User.query.get(session["user_id"])

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in [
        "png", "jpg", "jpeg", "gif", "webp"
    ]

def allowed_book_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in [
        "pdf", "epub", "docx", "txt"
    ]

def generate_ai_product_image(title, description):
    """Generate AI image for product"""
    prompt = f"""
    Professional marketplace product photo.
    Product: {title}.
    Description: {description}.
    Clean background, realistic, high quality.
    """
    
    try:
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
    except Exception as e:
        print(f"AI image generation error: {e}")
        return None

def expire_old_ads():
    """Expire old advertisements"""
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

# Context Processor
@app.context_processor
def inject_user():
    return {"user": current_user()}

# Routes
@app.route("/")
def home():
    expire_old_ads()
    
    search = request.args.get("search", "")
    category = request.args.get("category", "")
    
    products = Product.query.filter_by(is_active=True)
    
    if search:
        products = products.filter(Product.title.ilike(f"%{search}%"))
    
    if category:
        products = products.filter_by(category=category)
    
    products = products.all()
    
    return render_template(
        "index.html",
        products=products,
        search=search,
        category=category,
        categories=CATEGORIES
    )

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")
        
        user = User.query.filter_by(email=email).first()
        
        if user and check_password_hash(user.password_hash, password):
            session["user_id"] = user.id
            flash("تم تسجيل الدخول بنجاح")
            return redirect(url_for("home"))
        else:
            flash("البريد الإلكتروني أو كلمة المرور غير صحيحة")
    
    return render_template("login.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        full_name = request.form.get("full_name")
        email = request.form.get("email")
        password = request.form.get("password")
        
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            flash("هذا البريد الإلكتروني مسجل بالفعل")
            return redirect(url_for("register"))
        
        user = User(
            full_name=full_name,
            username=email,
            email=email,
            password_hash=generate_password_hash(password),
            credits=3
        )
        
        db.session.add(user)
        db.session.commit()
        
        session["user_id"] = user.id
        flash("تم إنشاء الحساب بنجاح")
        return redirect(url_for("home"))
    
    return render_template("register.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("تم تسجيل الخروج بنجاح")
    return redirect(url_for("home"))

@app.route("/google-login")
def google_login():
    redirect_uri = url_for("google_callback", _external=True)
    return google.authorize_redirect(redirect_uri)

@app.route("/auth/google/callback")
def google_callback():
    token = google.authorize_access_token()
    user_info = google.get("https://www.googleapis.com/oauth2/v2/userinfo").json()
    
    email = user_info.get("email")
    name = user_info.get("name")
    
    user = User.query.filter_by(email=email).first()
    
    if not user:
        user = User(
            full_name=name,
            username=email,
            email=email,
            password_hash="",
            credits=3
        )
        db.session.add(user)
        db.session.commit()
    
    session["user_id"] = user.id
    flash("تم تسجيل الدخول بنجاح")
    return redirect(url_for("home"))

@app.route("/plans")
def plans():
    return render_template("plans.html")

@app.route("/data-analysis", methods=["GET", "POST"])
def data_analysis():
    if "user_id" not in session:
        flash("يرجى تسجيل الدخول أولاً")
        return redirect(url_for("login"))
    
    if request.method == "POST":
        file = request.files.get("csv_file")
        
        if not file:
            flash("الرجاء رفع ملف CSV")
            return redirect(url_for("data_analysis"))
        
        if file.filename == "":
            flash("الرجاء اختيار ملف")
            return redirect(url_for("data_analysis"))
        
        if not file.filename.endswith(".csv"):
            flash("الرجاء رفع ملف CSV فقط")
            return redirect(url_for("data_analysis"))
        
        # Check file size
        file.seek(0, os.SEEK_END)
        file_size = file.tell()
        file.seek(0)
        
        if file_size > 500 * 1024 * 1024:
            flash("الملف كبير جداً (الحد الأقصى 500 ميجابايت)")
            return redirect(url_for("data_analysis"))
        
        os.makedirs("static/data_files", exist_ok=True)
        
        filename = secure_filename(file.filename)
        path = os.path.join("static/data_files", filename)
        file.save(path)
        
        try:
            # Try reading with different encodings
            try:
                df = pd.read_csv(path, encoding="utf-8")
            except:
                df = pd.read_csv(path, encoding="latin1")
            
            # Escape HTML special characters for security
            column_names = [html.escape(str(col)) for col in df.columns]
            
            result = {
                "rows": df.shape[0],
                "columns": df.shape[1],
                "column_names": column_names,
                "missing_values": {html.escape(str(k)): v for k, v in df.isnull().sum().to_dict().items()},
                "sample": df.head(10).to_html(classes="table", escape=True)
            }
            
            flash("تم تحليل الملف بنجاح")
            return render_template("data_analysis.html", result=result)
            
        except Exception as e:
            flash(f"حدث خطأ في قراءة الملف: {str(e)}")
            return redirect(url_for("data_analysis"))
    
    return render_template("data_analysis.html", result=None)

@app.route("/add-product", methods=["GET", "POST"])
def add_product():
    if "user_id" not in session:
        flash("يرجى تسجيل الدخول أولاً")
        return redirect(url_for("login"))
    
    if request.method == "POST":
        title = request.form.get("title")
        category = request.form.get("category") or "Other"
        price = request.form.get("price")
        description = request.form.get("description")
        city = request.form.get("city")
        
        if not title or not price:
            flash("الرجاء إدخال العنوان والسعر")
            return redirect(url_for("add_product"))
        
        image_file = request.files.get("image")
        filename = ""
        
        if image_file and image_file.filename and allowed_file(image_file.filename):
            os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
            filename = secure_filename(image_file.filename)
            save_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            image_file.save(save_path)
        
        generate_ai_img = request.form.get("generate_ai_image") == "on"
        
        if generate_ai_img and not filename and description:
            ai_filename = generate_ai_product_image(title, description)
            if ai_filename:
                filename = ai_filename
                flash("تم إنشاء صورة باستخدام الذكاء الاصطناعي")
        
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
        
        flash("تم إضافة المنتج بنجاح")
        return redirect(url_for("my_products"))
    
    return render_template("add_product.html", categories=CATEGORIES)

@app.route("/my-products")
def my_products():
    if "user_id" not in session:
        return redirect(url_for("login"))
    
    products = Product.query.filter_by(
        user_id=session["user_id"]
    ).order_by(Product.id.desc()).all()
    
    return render_template("my_products.html", products=products)

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
        flash("ليس لديك صلاحية لتعديل هذا المنتج")
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
        flash("تم تحديث المنتج بنجاح")
        return redirect(url_for("my_products"))
    
    return render_template("edit_product.html", product=product, categories=CATEGORIES)

@app.route("/my-products/delete/<int:product_id>")
def delete_product(product_id):
    if "user_id" not in session:
        return redirect(url_for("login"))
    
    product = Product.query.get_or_404(product_id)
    
    if product.user_id == session["user_id"]:
        db.session.delete(product)
        db.session.commit()
        flash("تم حذف المنتج بنجاح")
    
    return redirect(url_for("my_products"))

@app.route("/promote/<int:product_id>")
def promote_product(product_id):
    if "user_id" not in session:
        return redirect(url_for("login"))
    
    product = Product.query.get_or_404(product_id)
    
    if product.user_id != session["user_id"]:
        return redirect(url_for("my_products"))
    
    # Check if user has enough credits
    user = User.query.get(session["user_id"])
    if user.credits < 5:
        flash("لا يوجد رصيد كافي للترقية. يرجى شحن الرصيد")
        return redirect(url_for("payment"))
    
    product.is_featured = True
    product.is_ad = True
    product.ad_expire = datetime.utcnow() + timedelta(days=7)
    product.featured_requested = False
    
    user.credits -= 5
    db.session.commit()
    
    flash("تم ترقية المنتج لمدة 7 أيام")
    return redirect(url_for("my_products"))

@app.route("/generate-product-image/<int:product_id>")
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
        
        if filename:
            product.image_name = filename
            db.session.commit()
            flash("تم إنشاء صورة باستخدام الذكاء الاصطناعي بنجاح")
        else:
            flash("فشل إنشاء الصورة بالذكاء الاصطناعي")
    
    except Exception as e:
        print(f"AI IMAGE ERROR: {e}")
        flash("حدث خطأ في إنشاء الصورة")
    
    return redirect(url_for("my_products"))

# Admin Routes
@app.route("/admin", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        password = request.form.get("password")
        
        if password == ADMIN_PASSWORD:
            session["admin"] = True
            flash("تم تسجيل الدخول كمدير")
            return redirect(url_for("admin_dashboard"))
        
        flash("كلمة المرور غير صحيحة")
    
    return render_template("admin_login.html")

@app.route("/admin/dashboard")
def admin_dashboard():
    if not session.get("admin"):
        return redirect(url_for("admin_login"))
    
    products = Product.query.order_by(Product.id.desc()).all()
    payments = Payment.query.order_by(Payment.id.desc()).all()
    users = User.query.all()
    
    return render_template("admin.html", products=products, payments=payments, users=users)

@app.route("/admin/approve/<int:product_id>")
def approve_product(product_id):
    if not session.get("admin"):
        return redirect(url_for("admin_login"))
    
    product = Product.query.get_or_404(product_id)
    product.is_active = True
    product.is_rejected = False
    db.session.commit()
    
    flash("تم قبول المنتج")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/reject/<int:product_id>")
def reject_product(product_id):
    if not session.get("admin"):
        return redirect(url_for("admin_login"))
    
    product = Product.query.get_or_404(product_id)
    product.is_active = False
    product.is_rejected = True
    db.session.commit()
    
    flash("تم رفض المنتج")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/delete/<int:product_id>")
def admin_delete_product(product_id):
    if not session.get("admin"):
        return redirect(url_for("admin_login"))
    
    product = Product.query.get_or_404(product_id)
    db.session.delete(product)
    db.session.commit()
    
    flash("تم حذف المنتج")
    return redirect(url_for("admin_dashboard"))

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
    
    flash("تم قبول الإعلان المدفوع")
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
    
    flash("تم إزالة الإعلان المدفوع")
    return redirect(url_for("admin_dashboard"))

# Payment Routes
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
        
        flash("تم إرسال طلب الدفع بنجاح")
        return redirect(url_for("home"))
    
    return render_template("payment.html")

@app.route("/payment-success/<plan>")
def payment_success(plan):
    prices = {
        "starter": 50,
        "pro": 250,
        "basic": 20
    }
    
    credits = prices.get(plan, 0)
    
    if "user_id" in session:
        user = User.query.get(session["user_id"])
        if user:
            user.credits += credits
            db.session.commit()
            flash(f"تم إضافة {credits} رصيد إلى حسابك")
    
    return render_template("payment_success.html", credits=credits, plan=plan)

# AI Video Route
@app.route("/ai-video", methods=["GET", "POST"])
@login_required
def ai_video():
    user = current_user()

    if request.method == "POST":
        if user.credits <= 0:
            return redirect(url_for("payment"))

        prompt = request.form.get("prompt")

        try:
            output = replicate.run(
                "bytedance/seedance-1-lite",
                input={"prompt": prompt}
            )

            print("OUTPUT =", output)

            if isinstance(output, list):
                video_url = output[0]
            elif hasattr(output, "url") and callable(output.url):
                video_url = output.url()
            else:
                video_url = str(output)

            print("VIDEO URL =", video_url)

            user.credits -= 1
            db.session.commit()

            return render_template(
                "ai_video.html",
                credits=user.credits,
                video_url=video_url
            )

        except Exception as e:
            print("ERROR =", e)
            return f"ReplicateError Details: {e}"

    return render_template(
        "ai_video.html",
        credits=user.credits,
        video_url=None
    )

@app.route("/test-replicate")
def test_replicate():
    try:
        import replicate
        token = os.environ.get("REPLICATE_API_TOKEN", "غير موجود")
        return f"""
        <h1>اختبار Replicate</h1>
        <p>المكتبة: تم تحميلها بنجاح</p>
        <p>API Token: {'موجود ✅' if token != 'غير موجود' else 'غير موجود ❌'}</p>
        """
    except Exception as e:
        return f"خطأ: {str(e)}"
# Book Translation Route
@app.route("/book-translation")
def book_translation():
    return render_template("book_translation.html")

@app.route("/translate-book", methods=["POST"])
def translate_book():
    if "user_id" not in session:
        flash("يرجى تسجيل الدخول أولاً")
        return redirect(url_for("login"))
    
    if "book_file" not in request.files:
        flash("الرجاء رفع ملف")
        return redirect(url_for("book_translation"))
    
    file = request.files["book_file"]
    
    if file.filename == "":
        flash("الرجاء اختيار ملف")
        return redirect(url_for("book_translation"))
    
    # Validate file type
    if not allowed_book_file(file.filename):
        flash("الرجاء رفع ملف PDF أو EPUB أو DOCX أو TXT فقط")
        return redirect(url_for("book_translation"))
    
    # Check file size (max 50MB for books)
    file.seek(0, os.SEEK_END)
    file_size = file.tell()
    file.seek(0)
    
    if file_size > 50 * 1024 * 1024:
        flash("الملف كبير جداً (الحد الأقصى 50 ميجابايت)")
        return redirect(url_for("book_translation"))
    
    os.makedirs(app.config["BOOK_UPLOAD_FOLDER"], exist_ok=True)
    
    filename = secure_filename(file.filename)
    file_path = os.path.join(app.config["BOOK_UPLOAD_FOLDER"], filename)
    file.save(file_path)
    
    flash("تم رفع الملف بنجاح، جاري معالجة الترجمة...")
    
    return render_template(
        "translation_result.html",
        filename=filename,
        status="تم بدء معالجة الترجمة"
    )

# Add Credits Route
@app.route("/add-credits")
def add_credits():
    if "user_id" not in session:
        return redirect(url_for("login"))
    
    user = User.query.get(session["user_id"])
    user.credits += 10
    db.session.commit()
    
    flash("تم إضافة 10 رصيد إلى حسابك")
    return redirect(url_for("home"))

# Database Initialization
@app.route("/init-db")
def init_db():
    db.create_all()
    
    # Add missing columns for User table
    try:
        db.session.execute(text('ALTER TABLE "user" ADD COLUMN credits INTEGER DEFAULT 3'))
        db.session.commit()
    except Exception:
        db.session.rollback()
    
    try:
        db.session.execute(text('ALTER TABLE "user" ADD COLUMN plan VARCHAR(50) DEFAULT \'free\''))
        db.session.commit()
    except Exception:
        db.session.rollback()
    
    # Add missing columns for Product table
    try:
        db.session.execute(text("ALTER TABLE product ADD COLUMN IF NOT EXISTS is_ad BOOLEAN DEFAULT FALSE"))
        db.session.commit()
    except Exception:
        db.session.rollback()
    
    try:
        db.session.execute(text("ALTER TABLE product ADD COLUMN IF NOT EXISTS ad_expire TIMESTAMP"))
        db.session.commit()
    except Exception:
        db.session.rollback()
    
    try:
        db.session.execute(text("ALTER TABLE product ADD COLUMN IF NOT EXISTS is_featured BOOLEAN DEFAULT FALSE"))
        db.session.commit()
    except Exception:
        db.session.rollback()
    
    try:
        db.session.execute(text("ALTER TABLE product ADD COLUMN IF NOT EXISTS featured_requested BOOLEAN DEFAULT FALSE"))
        db.session.commit()
    except Exception:
        db.session.rollback()
    
    flash("تم تهيئة قاعدة البيانات بنجاح")
    return redirect(url_for("home"))

# Error Handlers
@app.errorhandler(404)
def not_found_error(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return render_template('500.html'), 500

# Create tables and run app
with app.app_context():
    db.create_all()

if __name__ == "__main__":
    app.run(debug=True)