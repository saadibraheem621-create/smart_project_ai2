from flask import Flask, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from datetime import datetime
import os
import requests

app = Flask(__name__)

app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-this-secret")
app.config["UPLOAD_FOLDER"] = "uploads"

db_url = os.environ.get("DATABASE_URL", "sqlite:///orders.db")
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_name = db.Column(db.String(100))
    whatsapp = db.Column(db.String(50))
    service = db.Column(db.String(100))
    notes = db.Column(db.Text)
    file_name = db.Column(db.String(200))
    status = db.Column(db.String(50), default="New")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


def send_telegram_message(text):
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        try:
            requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=10)
        except Exception:
            pass


@app.route("/")
def index():
    services = [
        {"name": "Data Analysis Report", "price": 50, "desc": "تحليل بيانات + تقرير PDF"},
        {"name": "Power BI Dashboard", "price": 70, "desc": "داشبورد احترافي"},
        {"name": "AI Model", "price": 100, "desc": "نموذج ذكاء اصطناعي"},
    ]
    return render_template("index.html", services=services)


@app.route("/order", methods=["GET", "POST"])
def order():
    if request.method == "POST":
        customer_name = request.form.get("customer_name")
        whatsapp = request.form.get("whatsapp")
        service = request.form.get("service")
        notes = request.form.get("notes")

        uploaded_file = request.files.get("file")
        file_name = None

        if uploaded_file and uploaded_file.filename:
            os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
            file_name = secure_filename(uploaded_file.filename)
            uploaded_file.save(os.path.join(app.config["UPLOAD_FOLDER"], file_name))

        new_order = Order(
            customer_name=customer_name,
            whatsapp=whatsapp,
            service=service,
            notes=notes,
            file_name=file_name
        )

        db.session.add(new_order)
        db.session.commit()

        send_telegram_message(
            f"طلب جديد\nالاسم: {customer_name}\nواتساب: {whatsapp}\nالخدمة: {service}"
        )

        return redirect(url_for("success"))

    return render_template("order.html")


@app.route("/success")
def success():
    return render_template("success.html")


@app.route("/admin")
def admin():
    orders = Order.query.order_by(Order.created_at.desc()).all()
    return render_template("admin.html", orders=orders)


@app.route("/update_status/<int:order_id>/<status>")
def update_status(order_id, status):
    order_item = Order.query.get_or_404(order_id)
    order_item.status = status
    db.session.commit()
    return redirect(url_for("admin"))


with app.app_context():
    db.create_all()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)