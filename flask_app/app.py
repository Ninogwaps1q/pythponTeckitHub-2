"""
Movie + Bus Ticketing Platform
Flask Application with SQLAlchemy, PayMongo Payments (Card, GCash, PayMaya, PayPal), and Admin Panel
"""

import os, base64, io, html
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
from functools import wraps
import requests
import google.generativeai as genai
from dotenv import load_dotenv
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from flask_mail import Mail, Message
from sqlalchemy import text

try:
    import qrcode
except Exception:
    qrcode = None

# Load environment variables from .env file.
# override=True ensures local project .env is used even if stale shell env vars exist.
load_dotenv(override=True)

# Initialize Flask app
app = Flask(__name__, static_folder='static', static_url_path='/static')
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-change-in-production')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///ticketing.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# PayMongo configuration is read from environment via paymongo_headers()

# Google Generative AI configuration
GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY', 'AIzaSyBk3E9YGt3nEYDNVWp3n28jKks2kTa3PN0')
genai.configure(api_key=GOOGLE_API_KEY)

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Initialize extensions
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Configure Flask-Mail (update with your SMTP settings)
app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME', '')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD', '')
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_DEFAULT_SENDER', '')
mail = Mail(app)

# Serializer for password reset tokens
serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'])

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def paymongo_headers():
    """
    Returns the headers needed to authenticate with PayMongo API.
    Reads the secret key from environment variables for security.
    """
    secret_key = (
        os.environ.get("PAYMONGO_SECRET_KEY")
        or os.environ.get("PAYMONGO_API_KEY")
        or os.environ.get("PAYMOONGO_API_KEY")
    )
    if not secret_key:
        print("[PayMongo] WARNING: PAYMONGO_SECRET_KEY (or PAYMONGO_API_KEY/PAYMOONGO_API_KEY) not set in environment!")
        return {
            "Authorization": "Basic MISSING_KEY",
            "Content-Type": "application/json"
        }
    
    # PayMongo uses Basic Auth with the secret key as username, password is empty
    auth_str = f"{secret_key}:"
    auth_bytes = auth_str.encode("utf-8")
    auth_b64 = base64.b64encode(auth_bytes).decode("utf-8")
    
    return {
        "Authorization": f"Basic {auth_b64}",
        "Content-Type": "application/json"
    }


def parse_paymongo_error(resp_data):
    """
    Normalize PayMongo error payloads into a consistent shape.
    PayMongo may return either {"error": {...}} or {"errors": [{...}]}.
    """
    default_msg = "Unknown error"
    default_code = "unknown"

    if not isinstance(resp_data, dict):
        return default_msg, default_code, None

    error_obj = resp_data.get("error")
    if isinstance(error_obj, dict) and error_obj:
        error_msg = (
            error_obj.get("message")
            or error_obj.get("detail")
            or error_obj.get("title")
            or error_obj.get("description")
            or default_msg
        )
        error_code = error_obj.get("code") or error_obj.get("status") or default_code
        return str(error_msg), str(error_code), error_obj

    errors = resp_data.get("errors")
    if isinstance(errors, list) and errors:
        first_error = errors[0] if isinstance(errors[0], dict) else {}
        error_msg = (
            first_error.get("detail")
            or first_error.get("message")
            or first_error.get("title")
            or resp_data.get("message")
            or default_msg
        )
        error_code = (
            first_error.get("code")
            or first_error.get("status")
            or first_error.get("id")
            or default_code
        )
        return str(error_msg), str(error_code), errors

    top_level_msg = resp_data.get("message")
    if top_level_msg:
        return str(top_level_msg), default_code, resp_data

    return default_msg, default_code, resp_data if resp_data else None


CHECKOUT_METHOD_ALIASES = {
    "card": "card",
    "credit_card": "card",
    "debit_card": "card",
    "gcash": "gcash",
    "paymaya": "maya",
    "maya": "maya",
}

CHECKOUT_SUPPORTED_METHODS = {
    "card",
    "gcash",
    "maya",
}


def normalize_checkout_payment_method(method_name):
    raw_method = str(method_name or "").strip().lower()
    if not raw_method:
        return ""
    return CHECKOUT_METHOD_ALIASES.get(raw_method, raw_method)


def build_checkout_session_payload(
    amount_cents,
    booking_reference,
    success_url,
    cancel_url,
    payment_method_types,
    metadata=None,
    description=None,
    customer_email=None,
):
    line_item = {
        "currency": "PHP",
        "amount": int(amount_cents),
        "name": "TicketHub Booking",
        "quantity": 1,
    }

    if description:
        line_item["description"] = description

    attributes = {
        "line_items": [line_item],
        "payment_method_types": payment_method_types,
        "success_url": success_url,
        "cancel_url": cancel_url,
        "description": description or f"TicketHub Booking {booking_reference}",
        "reference_number": booking_reference,
        "metadata": metadata or {},
        "send_email_receipt": False,
        "show_description": True,
        "show_line_items": True,
    }

    if customer_email:
        attributes["customer_email"] = customer_email

    return {"data": {"attributes": attributes}}


def checkout_session_is_paid(checkout_payload):
    if not isinstance(checkout_payload, dict):
        return False

    data = checkout_payload.get("data", {})
    attrs = data.get("attributes", {}) if isinstance(data, dict) else {}
    if not isinstance(attrs, dict):
        return False

    direct_status = str(attrs.get("status", "")).strip().lower()
    if direct_status in {"paid", "succeeded", "completed"}:
        return True

    # PayMongo includes payment_intent info inside checkout session attributes.
    payment_intent = attrs.get("payment_intent", {})
    pi_attrs = payment_intent.get("attributes", {}) if isinstance(payment_intent, dict) else {}
    pi_status = str(pi_attrs.get("status", "")).strip().lower()
    if pi_status in {"paid", "succeeded", "captured", "completed"}:
        return True

    # Fallback: if a payment object exists with a successful status, treat as paid.
    payment_lists = []
    top_level_payments = attrs.get("payments")
    if isinstance(top_level_payments, list):
        payment_lists.extend(top_level_payments)
    nested_payments = pi_attrs.get("payments")
    if isinstance(nested_payments, list):
        payment_lists.extend(nested_payments)

    for payment in payment_lists:
        if isinstance(payment, str) and payment.strip():
            return True
        if not isinstance(payment, dict):
            continue
        payment_attrs = payment.get("attributes", {}) if isinstance(payment.get("attributes"), dict) else {}
        payment_status = str(payment_attrs.get("status", "")).strip().lower()
        if payment_status in {"paid", "succeeded", "captured", "completed"}:
            return True

    return False


def get_booking_for_request(booking_type, booking_id):
    if booking_type == 'movie':
        return MovieBooking.query.get_or_404(booking_id)
    if booking_type == 'bus':
        return BusBooking.query.get_or_404(booking_id)
    raise ValueError('Invalid booking type')


def get_booking_or_none(booking_type, booking_id):
    try:
        booking_id = int(booking_id)
    except Exception:
        return None

    if booking_type == 'movie':
        return MovieBooking.query.get(booking_id)
    if booking_type == 'bus':
        return BusBooking.query.get(booking_id)
    return None


def infer_booking_type(booking):
    if isinstance(booking, MovieBooking):
        return 'movie'
    if isinstance(booking, BusBooking):
        return 'bus'
    return None


def find_booking_from_metadata(metadata=None, payment_reference=None):
    metadata = metadata if isinstance(metadata, dict) else {}

    booking_type = str(metadata.get('booking_type') or '').strip().lower()
    booking_id = metadata.get('booking_id')
    booking_reference = str(metadata.get('booking_reference') or '').strip()
    booking = None

    if booking_type in ('movie', 'bus') and booking_id is not None:
        booking = get_booking_or_none(booking_type, booking_id)

    if not booking and booking_reference:
        booking = MovieBooking.query.filter_by(booking_reference=booking_reference).first()
        if not booking:
            booking = BusBooking.query.filter_by(booking_reference=booking_reference).first()

    if not booking and payment_reference:
        booking = MovieBooking.query.filter_by(payment_reference=payment_reference).first()
        if not booking:
            booking = BusBooking.query.filter_by(payment_reference=payment_reference).first()

    return booking, (booking_type if booking_type in ('movie', 'bus') else infer_booking_type(booking))


def mark_booking_paid(booking, booking_type=None, payment_method=None, payment_reference=None, completed_by=None):
    if not booking:
        return False

    booking_type = booking_type if booking_type in ('movie', 'bus') else infer_booking_type(booking)
    if booking_type not in ('movie', 'bus'):
        return False

    updated = False
    if payment_method and booking.payment_method != payment_method:
        booking.payment_method = payment_method
        updated = True

    if payment_reference and booking.payment_reference != payment_reference:
        booking.payment_reference = payment_reference
        updated = True

    already_paid = str(booking.payment_status or '').strip().lower() in ('paid', 'completed')
    if already_paid:
        if updated:
            db.session.commit()
        return False

    booking.payment_status = 'paid'

    if booking_type == 'movie':
        try:
            showtime = booking.showtime
            if showtime and showtime.available_seats is not None:
                showtime.available_seats = max(0, int(showtime.available_seats) - int(booking.num_tickets or 0))
        except Exception:
            pass
    else:
        try:
            schedule = booking.schedule
            if schedule and schedule.available_seats is not None:
                schedule.available_seats = max(0, int(schedule.available_seats) - int(booking.num_tickets or 0))
        except Exception:
            pass

    db.session.commit()

    log_payment_transaction(
        user_id=booking.user_id,
        booking_type=booking_type,
        booking_id=booking.id,
        booking_ref=booking.booking_reference,
        amount=booking.total_amount,
        payment_method=booking.payment_method or 'card',
        status='completed',
        source_id=booking.payment_reference,
        completed_by=completed_by
    )

    try:
        send_booking_confirmation_email(booking.user, booking_type, booking)
    except Exception as e:
        print(f"[Payment] Failed to send confirmation email: {str(e)}")

    return True


# ==================== PayMongo Helper Functions ====================

def pm_retrieve_checkout_session(checkout_session_id):
    """Retrieve a PayMongo Checkout Session."""
    try:
        resp = requests.get(
            f"https://api.paymongo.com/v1/checkout_sessions/{checkout_session_id}",
            headers=paymongo_headers(),
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"error": str(e)}


def pm_create_payment_intent(amount_cents, currency='PHP', metadata=None, description=None):
    """Create a PayMongo Payment Intent"""
    try:
        payload = {"data": {"attributes": {"amount": amount_cents, "currency": currency, "statement_descriptor": description or "TicketHub Booking"}}}
        if metadata:
            payload["data"]["attributes"]["metadata"] = metadata
        resp = requests.post('https://api.paymongo.com/v1/payment_intents', json=payload, headers=paymongo_headers(), timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"error": str(e)}

def pm_retrieve_payment_intent(intent_id):
    """Retrieve a PayMongo Payment Intent"""
    try:
        resp = requests.get(f'https://api.paymongo.com/v1/payment_intents/{intent_id}', headers=paymongo_headers(), timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"error": str(e)}

def pm_attach_payment_method_to_intent(intent_id, payment_method_id):
    """Attach a payment method to a payment intent"""
    try:
        payload = {"data": {"attributes": {"payment_method": payment_method_id, "client_key": os.environ.get("PAYMONGO_PUBLIC_KEY", "pk_test_PA4RzhxD9BadaUFoTkaaTLbf"), "return_url": None}}}
        resp = requests.post(f'https://api.paymongo.com/v1/payment_intents/{intent_id}/attach', json=payload, headers=paymongo_headers(), timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"error": str(e)}

def pm_create_payment_method(type_name, details):
    """Create a PayMongo Payment Method (card, ewallet, bank_transfer)"""
    try:
        payload = {"data": {"attributes": {"type": type_name, "details": details}}}
        resp = requests.post('https://api.paymongo.com/v1/payment_methods', json=payload, headers=paymongo_headers(), timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"error": str(e)}

def pm_retrieve_payment_method(method_id):
    """Retrieve a PayMongo Payment Method"""
    try:
        resp = requests.get(f'https://api.paymongo.com/v1/payment_methods/{method_id}', headers=paymongo_headers(), timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"error": str(e)}

def pm_update_payment_method(method_id, metadata=None):
    """Update a PayMongo Payment Method"""
    try:
        payload = {"data": {"attributes": {}}}
        if metadata:
            payload["data"]["attributes"]["metadata"] = metadata
        resp = requests.post(f'https://api.paymongo.com/v1/payment_methods/{method_id}', json=payload, headers=paymongo_headers(), timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"error": str(e)}

def pm_retrieve_payment(payment_id):
    """Retrieve a PayMongo Payment"""
    try:
        resp = requests.get(f'https://api.paymongo.com/v1/payments/{payment_id}', headers=paymongo_headers(), timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"error": str(e)}

def pm_list_payments(limit=20, after=None):
    """List all PayMongo Payments"""
    try:
        params = {"limit": limit}
        if after:
            params["after"] = after
        resp = requests.get('https://api.paymongo.com/v1/payments', headers=paymongo_headers(), params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"error": str(e)}

def pm_create_refund(payment_id, amount_cents=None, reason=None, notes=None):
    """Create a PayMongo Refund"""
    try:
        payload = {"data": {"attributes": {"payment_id": payment_id}}}
        if amount_cents:
            payload["data"]["attributes"]["amount"] = amount_cents
        if reason:
            payload["data"]["attributes"]["reason"] = reason
        if notes:
            payload["data"]["attributes"]["notes"] = notes
        resp = requests.post('https://api.paymongo.com/v1/refunds', json=payload, headers=paymongo_headers(), timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"error": str(e)}

def pm_retrieve_refund(refund_id):
    """Retrieve a PayMongo Refund"""
    try:
        resp = requests.get(f'https://api.paymongo.com/v1/refunds/{refund_id}', headers=paymongo_headers(), timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"error": str(e)}

def pm_list_refunds(limit=20, after=None):
    """List all PayMongo Refunds"""
    try:
        params = {"limit": limit}
        if after:
            params["after"] = after
        resp = requests.get('https://api.paymongo.com/v1/refunds', headers=paymongo_headers(), params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"error": str(e)}

def pm_create_customer(email, phone=None, first_name=None, last_name=None, metadata=None):
    """Create a PayMongo Customer"""
    try:
        payload = {"data": {"attributes": {"email": email}}}
        if phone:
            payload["data"]["attributes"]["phone"] = phone
        if first_name:
            payload["data"]["attributes"]["first_name"] = first_name
        if last_name:
            payload["data"]["attributes"]["last_name"] = last_name
        if metadata:
            payload["data"]["attributes"]["metadata"] = metadata
        resp = requests.post('https://api.paymongo.com/v1/customers', json=payload, headers=paymongo_headers(), timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"error": str(e)}

def pm_retrieve_customer(customer_id):
    """Retrieve a PayMongo Customer"""
    try:
        resp = requests.get(f'https://api.paymongo.com/v1/customers/{customer_id}', headers=paymongo_headers(), timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"error": str(e)}

def pm_update_customer(customer_id, email=None, phone=None, first_name=None, last_name=None, metadata=None):
    """Update a PayMongo Customer"""
    try:
        payload = {"data": {"attributes": {}}}
        if email:
            payload["data"]["attributes"]["email"] = email
        if phone:
            payload["data"]["attributes"]["phone"] = phone
        if first_name:
            payload["data"]["attributes"]["first_name"] = first_name
        if last_name:
            payload["data"]["attributes"]["last_name"] = last_name
        if metadata:
            payload["data"]["attributes"]["metadata"] = metadata
        resp = requests.post(f'https://api.paymongo.com/v1/customers/{customer_id}', json=payload, headers=paymongo_headers(), timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"error": str(e)}

def pm_list_customers(limit=20, after=None):
    """List all PayMongo Customers"""
    try:
        params = {"limit": limit}
        if after:
            params["after"] = after
        resp = requests.get('https://api.paymongo.com/v1/customers', headers=paymongo_headers(), params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"error": str(e)}


# ==================== DATABASE MODELS ====================

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20))
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    movie_bookings = db.relationship('MovieBooking', backref='user', lazy=True)
    bus_bookings = db.relationship('BusBooking', backref='user', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Movie(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    genre = db.Column(db.String(100))
    duration = db.Column(db.Integer)  # in minutes
    rating = db.Column(db.String(10))  # PG, PG-13, R, etc.
    poster_image = db.Column(db.String(255))
    trailer_url = db.Column(db.String(255))
    release_date = db.Column(db.Date)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    showtimes = db.relationship('Showtime', backref='movie', lazy=True, cascade='all, delete-orphan')


class Cinema(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    location = db.Column(db.String(200))
    total_seats = db.Column(db.Integer, default=100)
    
    showtimes = db.relationship('Showtime', backref='cinema', lazy=True)


class Showtime(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    movie_id = db.Column(db.Integer, db.ForeignKey('movie.id'), nullable=False)
    cinema_id = db.Column(db.Integer, db.ForeignKey('cinema.id'), nullable=False)
    show_date = db.Column(db.Date, nullable=False)
    show_time = db.Column(db.Time, nullable=False)
    price = db.Column(db.Float, nullable=False)
    available_seats = db.Column(db.Integer)
    
    bookings = db.relationship('MovieBooking', backref='showtime', lazy=True)


class MovieBooking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    showtime_id = db.Column(db.Integer, db.ForeignKey('showtime.id'), nullable=False)
    num_tickets = db.Column(db.Integer, nullable=False)
    seat_numbers = db.Column(db.String(200))
    total_amount = db.Column(db.Float, nullable=False)
    payment_status = db.Column(db.String(20), default='pending')  # pending, completed, failed, refunded

    payment_method = db.Column(db.String(20))     # 'card', 'gcash', 'paymaya', 'paypal'
    payment_reference = db.Column(db.String(255)) # PayMongo source/payment id

    booking_reference = db.Column(db.String(20), unique=True)
    is_verified = db.Column(db.Boolean, default=False, nullable=False)
    verified_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class BusRoute(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    origin = db.Column(db.String(100), nullable=False)
    destination = db.Column(db.String(100), nullable=False)
    bus_operator = db.Column(db.String(100))
    bus_type = db.Column(db.String(50))  # AC, Non-AC, Sleeper, etc.
    departure_time = db.Column(db.Time, nullable=False)
    arrival_time = db.Column(db.Time, nullable=False)
    duration = db.Column(db.String(50))
    price = db.Column(db.Float, nullable=False)
    total_seats = db.Column(db.Integer, default=40)
    amenities = db.Column(db.String(255))  # WiFi, Charging, etc.
    is_active = db.Column(db.Boolean, default=True)
    
    schedules = db.relationship('BusSchedule', backref='route', lazy=True)


class BusSchedule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    route_id = db.Column(db.Integer, db.ForeignKey('bus_route.id'), nullable=False)
    travel_date = db.Column(db.Date, nullable=False)
    available_seats = db.Column(db.Integer)
    
    bookings = db.relationship('BusBooking', backref='schedule', lazy=True)


class BusBooking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    schedule_id = db.Column(db.Integer, db.ForeignKey('bus_schedule.id'), nullable=False)
    num_tickets = db.Column(db.Integer, nullable=False)
    seat_numbers = db.Column(db.String(200))
    passenger_names = db.Column(db.Text)
    total_amount = db.Column(db.Float, nullable=False)
    payment_status = db.Column(db.String(20), default='pending')  # pending, completed, failed, refunded

    payment_method = db.Column(db.String(20))     # 'card', 'gcash', 'paymaya', 'paypal'
    payment_reference = db.Column(db.String(255)) # PayMongo source/payment id

    booking_reference = db.Column(db.String(20), unique=True)
    is_verified = db.Column(db.Boolean, default=False, nullable=False)
    verified_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class PaymentTransaction(db.Model):
    """Log all payment transactions for audit trail"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    booking_type = db.Column(db.String(20), nullable=False)  # 'movie' or 'bus'
    booking_id = db.Column(db.Integer, nullable=False)
    booking_reference = db.Column(db.String(20), nullable=False)
    
    amount = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(3), default='PHP')
    payment_method = db.Column(db.String(20), nullable=False)  # card, gcash, paymaya, paypal
    payment_status = db.Column(db.String(20), nullable=False)  # pending, completed, failed
    
    payment_source_id = db.Column(db.String(255))  # PayMongo source ID
    
    # Who completed the payment (user id). Only set when status is not 'pending'
    completed_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    completed_by_user = db.relationship('User', foreign_keys=[completed_by], backref='completed_transactions')
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    user = db.relationship('User', foreign_keys=[user_id], backref='payment_transactions')

# ==================== PAYMENT TRANSACTION LOGGING ====================

def log_payment_transaction(user_id, booking_type, booking_id, booking_ref, amount, payment_method, status, source_id=None, completed_by=None):
    """Log a payment transaction for audit trail.

    `completed_by` will only be recorded when `status` is not 'pending'.
    """
    # Only record successful/paid transactions in the audit table.
    # Skip any status that is not a completed/paid state (e.g., 'pending', 'failed', 'cancelled').
    if not status or status.lower() not in ('completed', 'paid', 'succeeded', 'captured'):
        return None

    try:
        transaction = PaymentTransaction(
            user_id=user_id,
            booking_type=booking_type,
            booking_id=booking_id,
            booking_reference=booking_ref,
            amount=amount,
            payment_method=payment_method,
            payment_status=status,
            payment_source_id=source_id,
        )

        # Only set completed_by for non-pending statuses and when provided
        if status and status.lower() != 'pending' and completed_by:
            transaction.completed_by = completed_by

        db.session.add(transaction)
        db.session.commit()
        return transaction.id
    except Exception as e:
        print(f"Error logging payment transaction: {str(e)}")
        return None


# ==================== EMAIL FUNCTIONS ====================

def is_booking_paid(booking):
    """Return True if booking has a completed payment status."""
    return str(getattr(booking, 'payment_status', '') or '').strip().lower() in ('paid', 'completed')


def generate_ticket_scan_token(booking_type, booking):
    """Create a signed token used by ticket QR scanning."""
    payload = {
        'booking_type': str(booking_type or '').strip().lower(),
        'booking_id': int(getattr(booking, 'id', 0) or 0),
        'booking_reference': str(getattr(booking, 'booking_reference', '') or '').strip(),
    }
    return serializer.dumps(payload, salt='ticket-qr-salt')


def build_ticket_scan_url(booking_type, booking, external=True):
    """Build scan URL containing a signed token for verification."""
    token = generate_ticket_scan_token(booking_type, booking)
    try:
        return url_for('scan_ticket_qr', token=token, _external=external)
    except Exception:
        # Fallback when no request context/base URL is available.
        return f"/ticket/scan/{token}"


def generate_qr_png_bytes(payload_text):
    """Generate QR PNG bytes for text/url payload."""
    if not payload_text or not qrcode:
        return None
    try:
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=2
        )
        qr.add_data(str(payload_text))
        qr.make(fit=True)
        image = qr.make_image(fill_color='black', back_color='white')
        buf = io.BytesIO()
        image.save(buf, format='PNG')
        return buf.getvalue()
    except Exception as e:
        print(f"[QR] Failed to generate QR image: {str(e)}")
        return None


def build_qr_data_uri(png_bytes):
    """Convert PNG bytes to data URI for inline HTML rendering."""
    if not png_bytes:
        return None
    return "data:image/png;base64," + base64.b64encode(png_bytes).decode('ascii')


def build_ticket_qr_payload(booking_type, booking):
    """Human-readable QR payload with booking details only (no URL)."""
    bt = str(booking_type or '').strip().lower()
    lines = [
        "TicketHub eTicket",
        f"Reference: {getattr(booking, 'booking_reference', '')}",
        f"Type: {bt.upper()}",
        f"Status: {str(getattr(booking, 'payment_status', '') or '').upper() or 'PENDING'}",
    ]

    try:
        if bt == 'movie':
            showtime = booking.showtime
            movie = showtime.movie
            cinema = showtime.cinema
            seat_display = movie_seat_list_to_display(booking.seat_numbers) if booking.seat_numbers else 'To be assigned'
            lines.extend([
                f"Movie: {movie.title}",
                f"Cinema: {cinema.name}",
                f"Date: {showtime.show_date.strftime('%Y-%m-%d')}",
                f"Time: {showtime.show_time.strftime('%I:%M %p')}",
                f"Tickets: {booking.num_tickets}",
                f"Seats: {seat_display}",
            ])
        elif bt == 'bus':
            schedule = booking.schedule
            route = schedule.route
            lines.extend([
                f"Route: {route.origin} -> {route.destination}",
                f"Travel Date: {schedule.travel_date.strftime('%Y-%m-%d')}",
                f"Departure: {route.departure_time.strftime('%I:%M %p')}",
                f"Passengers: {booking.num_tickets}",
                f"Seats: {booking.seat_numbers or 'To be assigned'}",
            ])
    except Exception:
        # Keep payload generation resilient.
        pass

    return "\n".join(lines)


def get_qr_ticket_context(booking_type, booking):
    """Return scan URL and QR representations for templates/emails."""
    scan_url = build_ticket_scan_url(booking_type, booking, external=True)
    qr_payload = scan_url
    qr_png_bytes = generate_qr_png_bytes(qr_payload)
    return {
        'scan_url': scan_url,
        'qr_payload': qr_payload,
        'qr_png_bytes': qr_png_bytes,
        'qr_data_uri': build_qr_data_uri(qr_png_bytes),
    }


def send_booking_confirmation_email(user, booking_type, booking):
    """Send booking confirmation email to user with QR ticket."""
    try:
        booking_type = str(booking_type or '').strip().lower()
        qr_ctx = get_qr_ticket_context(booking_type, booking)
        ticket_scan_url = qr_ctx.get('scan_url')
        qr_png_bytes = qr_ctx.get('qr_png_bytes')

        payment_method = str(getattr(booking, 'payment_method', '') or 'ONLINE').upper()
        payment_status = str(getattr(booking, 'payment_status', '') or '').upper() or 'PAID'

        if booking_type == 'movie':
            showtime = booking.showtime
            movie = showtime.movie
            cinema = showtime.cinema
            seat_display = movie_seat_list_to_display(booking.seat_numbers) if booking.seat_numbers else 'To be assigned'
            subject = f"Movie Booking Confirmed - {booking.booking_reference}"
            detail_rows = [
                ("Booking Reference", booking.booking_reference),
                ("Movie", movie.title),
                ("Cinema", cinema.name),
                ("Date", showtime.show_date.strftime('%B %d, %Y')),
                ("Time", showtime.show_time.strftime('%I:%M %p')),
                ("Tickets", str(booking.num_tickets)),
                ("Seats", seat_display),
                ("Amount Paid", f"PHP {booking.total_amount:.2f}"),
                ("Payment Method", payment_method),
                ("Status", payment_status),
            ]
            travel_note = "Please arrive 15 minutes before showtime and present your QR code or booking reference."
        else:
            schedule = booking.schedule
            route = schedule.route
            subject = f"Bus Booking Confirmed - {booking.booking_reference}"
            detail_rows = [
                ("Booking Reference", booking.booking_reference),
                ("Route", f"{route.origin} -> {route.destination}"),
                ("Bus Operator", route.bus_operator or "N/A"),
                ("Bus Type", route.bus_type or "Standard"),
                ("Travel Date", schedule.travel_date.strftime('%B %d, %Y')),
                ("Departure", route.departure_time.strftime('%I:%M %p')),
                ("Arrival", route.arrival_time.strftime('%I:%M %p')),
                ("Passengers", str(booking.num_tickets)),
                ("Seats", booking.seat_numbers or "To be assigned"),
                ("Amount Paid", f"PHP {booking.total_amount:.2f}"),
                ("Payment Method", payment_method),
                ("Status", payment_status),
            ]
            travel_note = "Please arrive 30 minutes before departure and present your QR code or booking reference."

        detail_lines_text = "\n".join(f"{k}: {v}" for k, v in detail_rows)
        detail_rows_html = "".join(
            f"<tr><td style='padding:6px 0;color:#6b7280;'>{html.escape(str(k))}</td>"
            f"<td style='padding:6px 0;font-weight:600;text-align:right;'>{html.escape(str(v))}</td></tr>"
            for k, v in detail_rows
        )
        qr_instruction_text = (
            "Scan the QR code attached in this email to verify your booking at check-in."
            if qr_png_bytes else
            "Use the verification link below to verify your booking at check-in."
        )

        body_text = (
            f"Hello {user.name},\n\n"
            "Your booking is confirmed.\n\n"
            f"{detail_lines_text}\n\n"
            f"{qr_instruction_text}\n"
            f"Ticket verification link: {ticket_scan_url}\n\n"
            f"{travel_note}\n\n"
            "TicketHub Team"
        )

        qr_section_html = (
            "<p style='margin:16px 0 8px;'>A QR code image is attached to this email for check-in scanning.</p>"
            if qr_png_bytes else
            "<p style='margin:16px 0 8px;'>QR generation is unavailable right now. Use the verification link below.</p>"
        )

        body_html = (
            f"<div style='font-family:Arial, sans-serif; max-width:560px;'>"
            f"<h2 style='margin:0 0 10px;'>Booking Confirmed</h2>"
            f"<p style='margin:0 0 16px;'>Hello {html.escape(str(user.name))}, your booking is confirmed.</p>"
            f"<table style='width:100%;border-collapse:collapse;'>{detail_rows_html}</table>"
            f"<hr style='margin:18px 0;border:none;border-top:1px solid #e5e7eb;'>"
            f"{qr_section_html}"
            f"<p style='margin:12px 0 6px;'>Verification link:</p>"
            f"<p style='margin:0 0 16px;word-break:break-all;'><a href='{html.escape(str(ticket_scan_url))}'>{html.escape(str(ticket_scan_url))}</a></p>"
            f"<p style='margin:0 0 16px;color:#4b5563;'>{html.escape(travel_note)}</p>"
            f"<p style='margin:0;color:#6b7280;'>TicketHub Team</p>"
            f"</div>"
        )

        msg = Message(
            subject=subject,
            recipients=[user.email],
            body=body_text,
            html=body_html
        )

        if qr_png_bytes:
            # Attach QR PNG so user can scan from email.
            msg.attach(
                filename=f"{booking.booking_reference}_qr.png",
                content_type='image/png',
                data=qr_png_bytes,
                disposition='attachment'
            )

        mail.send(msg)
        print(f"[Email] Booking confirmation sent to {user.email} (Ref: {booking.booking_reference})")
        return True
    except Exception as e:
        print(f"[Email] Failed to send booking confirmation email: {str(e)}")
        return False


def send_booking_verified_email(user, booking_type, booking, verified_at=None):
    """Send a follow-up email when a ticket is scanned and marked verified."""
    try:
        booking_type = str(booking_type or '').strip().lower()
        verified_at = verified_at or getattr(booking, 'verified_at', None) or datetime.now()

        if booking_type == 'movie':
            showtime = booking.showtime
            seat_display = movie_seat_list_to_display(booking.seat_numbers) if booking.seat_numbers else 'To be assigned'
            subject = f"Ticket Verified - {booking.booking_reference}"
            detail_rows = [
                ("Booking Reference", booking.booking_reference),
                ("Type", "MOVIE"),
                ("Movie", showtime.movie.title),
                ("Cinema", showtime.cinema.name),
                ("Showtime", f"{showtime.show_date.strftime('%b %d, %Y')} {showtime.show_time.strftime('%I:%M %p')}"),
                ("Seats", seat_display),
                ("Verified At", verified_at.strftime('%b %d, %Y %I:%M %p')),
            ]
        else:
            schedule = booking.schedule
            route = schedule.route
            subject = f"Ticket Verified - {booking.booking_reference}"
            detail_rows = [
                ("Booking Reference", booking.booking_reference),
                ("Type", "BUS"),
                ("Route", f"{route.origin} -> {route.destination}"),
                ("Travel Date", schedule.travel_date.strftime('%b %d, %Y')),
                ("Departure", route.departure_time.strftime('%I:%M %p')),
                ("Seats", booking.seat_numbers or "To be assigned"),
                ("Verified At", verified_at.strftime('%b %d, %Y %I:%M %p')),
            ]

        detail_lines_text = "\n".join(f"{k}: {v}" for k, v in detail_rows)
        detail_rows_html = "".join(
            f"<tr><td style='padding:6px 0;color:#6b7280;'>{html.escape(str(k))}</td>"
            f"<td style='padding:6px 0;font-weight:600;text-align:right;'>{html.escape(str(v))}</td></tr>"
            for k, v in detail_rows
        )

        body_text = (
            f"Hello {user.name},\n\n"
            "Your ticket has been scanned and verified.\n\n"
            f"{detail_lines_text}\n\n"
            "If this was not you, please contact support immediately.\n\n"
            "TicketHub Team"
        )

        body_html = (
            f"<div style='font-family:Arial, sans-serif; max-width:560px;'>"
            f"<h2 style='margin:0 0 10px;'>Ticket Verified</h2>"
            f"<p style='margin:0 0 16px;'>Hello {html.escape(str(user.name))}, your ticket has been scanned and verified.</p>"
            f"<table style='width:100%;border-collapse:collapse;'>{detail_rows_html}</table>"
            f"<p style='margin:16px 0 0;color:#4b5563;'>If this was not you, please contact support immediately.</p>"
            f"<p style='margin:8px 0 0;color:#6b7280;'>TicketHub Team</p>"
            f"</div>"
        )

        msg = Message(
            subject=subject,
            recipients=[user.email],
            body=body_text,
            html=body_html
        )
        mail.send(msg)
        print(f"[Email] Verification notice sent to {user.email} (Ref: {booking.booking_reference})")
        return True
    except Exception as e:
        print(f"[Email] Failed to send verification notice: {str(e)}")
        return False


# ==================== HELPER FUNCTIONS ====================

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('You need admin access for this action.', 'error')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function


def generate_booking_reference():
    import random
    import string
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))


def normalize_multi_value(values):
    """Normalize multi-select or comma-separated values into a canonical ', ' string.

    Accepts a list/tuple/set (from request.form.getlist) or a string.
    Returns None if no non-empty values are provided.
    """
    if values is None:
        return None

    items = []
    if isinstance(values, (list, tuple, set)):
        for v in values:
            if v is None:
                continue
            s = str(v).strip()
            if not s:
                continue
            items.append(s)
    else:
        # Backward compatible: allow comma-separated strings.
        s = str(values).strip()
        if s:
            items.extend([p.strip() for p in s.split(',') if p and p.strip()])

    # De-dupe while preserving order (case-insensitive).
    seen = set()
    out = []
    for it in items:
        key = it.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(it)

    return ', '.join(out) if out else None


def get_showtime_total_seats(showtime):
    """Return the seat capacity for a showtime (prefer cinema.total_seats)."""
    try:
        if showtime.cinema and showtime.cinema.total_seats:
            return int(showtime.cinema.total_seats)
    except Exception:
        pass
    return int(showtime.available_seats or 0)


def get_reserved_movie_seats(showtime_id, statuses=None):
    """Return (reserved_seat_set, unknown_reserved_count) for a showtime.

    Seats are considered reserved if the booking is in a reserved payment status.
    If a booking has no explicit seat_numbers, we account for its num_tickets as
    unknown reservations for availability counting.
    """
    if not statuses:
        statuses = ['pending', 'paid', 'completed']

    reserved = set()
    unknown = 0
    bookings = MovieBooking.query.filter(
        MovieBooking.showtime_id == showtime_id,
        MovieBooking.payment_status.in_(statuses)
    ).all()

    for b in bookings:
        if b.seat_numbers:
            for s in b.seat_numbers.split(','):
                s2 = (s or '').strip()
                if s2:
                    reserved.add(s2)
        else:
            unknown += int(b.num_tickets or 0)

    return reserved, unknown


def get_reserved_bus_seats(schedule_id, statuses=None):
    """Return (reserved_seat_set, unknown_reserved_count) for a bus schedule.

    Seats are considered reserved if the booking is in a reserved payment status.
    If a booking has no explicit seat_numbers, we account for its num_tickets as
    unknown reservations for availability counting.
    """
    if not statuses:
        statuses = ['pending', 'paid', 'completed']

    reserved = set()
    unknown = 0
    bookings = BusBooking.query.filter(
        BusBooking.schedule_id == schedule_id,
        BusBooking.payment_status.in_(statuses)
    ).all()

    for b in bookings:
        if b.seat_numbers:
            for s in b.seat_numbers.split(','):
                s2 = (s or '').strip()
                if s2:
                    reserved.add(s2)
        else:
            unknown += int(b.num_tickets or 0)

    return reserved, unknown


def is_valid_showtime_seat_label(seat_label, total_seats, cols=10):
    """Validate 'row-col' label within 1..total_seats given fixed column count."""
    try:
        parts = str(seat_label).split('-')
        if len(parts) != 2:
            return False
        r = int(parts[0])
        c = int(parts[1])
        if r <= 0 or c <= 0 or c > cols:
            return False
        seat_index = (r - 1) * cols + c
        return 1 <= seat_index <= int(total_seats or 0)
    except Exception:
        return False


def seat_row_to_letters(row_num):
    """Convert 1-based row number to letters (1->A, 26->Z, 27->AA)."""
    try:
        n = int(row_num)
    except Exception:
        return ''
    if n <= 0:
        return ''
    out = ''
    while n > 0:
        n, rem = divmod(n - 1, 26)
        out = chr(65 + rem) + out
    return out


def movie_seat_label_to_display(seat_label):
    """Convert internal movie seat code 'row-col' to user label like 'A1'."""
    try:
        parts = str(seat_label or '').strip().split('-')
        if len(parts) != 2:
            return str(seat_label or '').strip()
        row = int(parts[0])
        col = int(parts[1])
        if row <= 0 or col <= 0:
            return str(seat_label or '').strip()
        row_letters = seat_row_to_letters(row)
        if not row_letters:
            return str(seat_label or '').strip()
        return f'{row_letters}{col}'
    except Exception:
        return str(seat_label or '').strip()


def movie_seat_list_to_display(seat_numbers):
    """Convert comma-separated internal seat codes to display labels."""
    seats = [s.strip() for s in str(seat_numbers or '').split(',') if s and s.strip()]
    if not seats:
        return ''
    return ', '.join(movie_seat_label_to_display(s) for s in seats)


@app.template_filter('movie_seat_label')
def movie_seat_label_filter(value):
    return movie_seat_label_to_display(value)


@app.template_filter('movie_seat_list')
def movie_seat_list_filter(value):
    return movie_seat_list_to_display(value)


def parse_travel_date(value, default_date=None):
    """Parse YYYY-MM-DD travel date; fallback to default_date or today."""
    try:
        return datetime.strptime(str(value or ''), '%Y-%m-%d').date()
    except Exception:
        return default_date or datetime.now().date()


def is_route_departed_for_date(route, travel_date, now_dt=None):
    """True when route should be unavailable for booking on a given travel date.

    Rules:
    - Past travel dates are unavailable.
    - Future travel dates are available.
    - For today, route is unavailable only while bus is in transit
      (departure <= now < arrival). After arrival, it becomes available again.
    """
    if not route or not getattr(route, 'departure_time', None) or not travel_date:
        return False
    now_dt = now_dt or datetime.now()
    if travel_date < now_dt.date():
        return True
    if travel_date > now_dt.date():
        return False
    departure_dt = datetime.combine(travel_date, route.departure_time)

    # If arrival_time is earlier than departure_time, treat it as next-day arrival.
    arrival_time = getattr(route, 'arrival_time', None) or route.departure_time
    arrival_dt = datetime.combine(travel_date, arrival_time)
    if arrival_dt <= departure_dt:
        arrival_dt = arrival_dt + timedelta(days=1)

    return departure_dt <= now_dt < arrival_dt


def is_showtime_departed(showtime, now_dt=None):
    """True when movie showtime has already started/passed."""
    if not showtime or not getattr(showtime, 'show_date', None) or not getattr(showtime, 'show_time', None):
        return False
    now_dt = now_dt or datetime.now()
    show_dt = datetime.combine(showtime.show_date, showtime.show_time)
    return show_dt <= now_dt


# ==================== ROUTES - MAIN ====================

@app.route('/')
def index():
    movies = Movie.query.filter_by(is_active=True).order_by(Movie.release_date.desc()).limit(6).all()
    today = datetime.now().date()
    all_routes = BusRoute.query.filter_by(is_active=True).order_by(BusRoute.departure_time).all()
    routes = [r for r in all_routes if not is_route_departed_for_date(r, today)][:6]

    # Build availability maps for movies (next upcoming showtime) and bus routes (next schedule)
    availability_map = {}
    for m in movies:
        try:
            candidate_shows = Showtime.query.filter(
                Showtime.movie_id == m.id,
                Showtime.show_date >= datetime.now().date()
            ).order_by(Showtime.show_date, Showtime.show_time).all()
            next_show = next((st for st in candidate_shows if not is_showtime_departed(st)), None)
            if not next_show:
                continue

            # determine total seats for the showtime
            try:
                total_seats = int(next_show.cinema.total_seats) if next_show.cinema and next_show.cinema.total_seats else int(next_show.available_seats or 0)
            except Exception:
                total_seats = int(next_show.available_seats or 0)

            # count reserved seats (pending/paid/completed)
            reserved = 0
            statuses = ['pending', 'paid', 'completed']
            bookings = MovieBooking.query.filter(MovieBooking.showtime_id == next_show.id, MovieBooking.payment_status.in_(statuses)).all()
            for b in bookings:
                if b.seat_numbers:
                    reserved += len([s for s in b.seat_numbers.split(',') if s.strip()])
                else:
                    reserved += int(b.num_tickets or 0)

            available = max(0, total_seats - reserved)
            availability_map[m.id] = {
                'showtime_id': next_show.id,
                'show_date': next_show.show_date.isoformat(),
                'show_time': next_show.show_time.strftime('%I:%M %p') if next_show.show_time else None,
                'total_seats': total_seats,
                'reserved': reserved,
                'available': available
            }
        except Exception as e:
            print(f"[Index] Error computing availability for movie {m.id}: {e}")

    route_availability = {}
    for r in routes:
        try:
            sched = BusSchedule.query.filter(
                BusSchedule.route_id == r.id,
                BusSchedule.travel_date >= datetime.now().date()
            ).order_by(BusSchedule.travel_date).first()
            if not sched:
                continue

            total = int(r.total_seats or sched.available_seats or 0)
            reserved = 0
            statuses = ['pending', 'paid', 'completed']
            bks = BusBooking.query.filter(BusBooking.schedule_id == sched.id, BusBooking.payment_status.in_(statuses)).all()
            for b in bks:
                if b.seat_numbers:
                    reserved += len([s for s in b.seat_numbers.split(',') if s.strip()])
                else:
                    reserved += int(b.num_tickets or 0)

            available = max(0, total - reserved)
            route_availability[r.id] = {
                'schedule_id': sched.id,
                'travel_date': sched.travel_date.isoformat(),
                'total_seats': total,
                'reserved': reserved,
                'available': available
            }
        except Exception as e:
            print(f"[Index] Error computing availability for route {r.id}: {e}")

    return render_template('index.html', movies=movies, routes=routes, availability_map=availability_map, route_availability=route_availability)


# ==================== ROUTES - AUTHENTICATION ====================

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        name = request.form.get('name')
        phone = request.form.get('phone')
        
        if User.query.filter_by(email=email).first():
            flash('Email already registered.', 'error')
            return redirect(url_for('register'))
        # Validate phone: must be exactly 11 digits (e.g., 09123456789)
        if phone:
            cleaned = ''.join(ch for ch in phone if ch.isdigit())
            if len(cleaned) != 11:
                flash('Phone number must be exactly 11 digits (e.g. 09123456789).', 'error')
                return redirect(url_for('register'))
            phone = cleaned
        
        user = User(email=email, name=name, phone=phone)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        
        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('login'))
    
    return render_template('auth/register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        user = User.query.filter_by(email=email).first()
        
        if user and user.check_password(password):
            login_user(user)
            next_page = request.args.get('next')
            flash('Welcome back!', 'success')
            return redirect(next_page or url_for('index'))
        
        flash('Invalid email or password.', 'error')
    
    return render_template('auth/login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))


# ==================== ROUTES - MOVIES ====================

@app.route('/movies')
def movies():
    selected_genre = (request.args.get('genre') or 'all').strip().lower()
    q = (request.args.get('q') or '').strip()

    query = Movie.query.filter_by(is_active=True)

    if q:
        query = query.filter(Movie.title.ilike(f'%{q}%'))

    if selected_genre and selected_genre != 'all':
        # Accept common variants and do a case-insensitive contains match so existing data like
        # "Action, Comedy" or "Sci Fi" still matches.
        genre_terms = [selected_genre]
        if selected_genre in ('sci-fi', 'scifi', 'sci_fi', 'sci fi', 'sci'):
            genre_terms = ['sci-fi', 'sci fi', 'scifi', 'sci_fi', 'science fiction']
        from sqlalchemy import or_
        genre_filters = [Movie.genre.ilike(f'%{t}%') for t in genre_terms]
        query = query.filter(or_(*genre_filters))

    movies = query.order_by(Movie.release_date.desc()).all()
    return render_template(
        'movies/list.html',
        movies=movies,
        selected_genre=selected_genre,
        q=q
    )


@app.route('/movies/<int:movie_id>')
def movie_detail(movie_id):
    movie = Movie.query.get_or_404(movie_id)
    showtimes = Showtime.query.filter(
        Showtime.movie_id == movie_id,
        Showtime.show_date >= datetime.now().date()
    ).order_by(Showtime.show_date, Showtime.show_time).all()
    showtimes = [st for st in showtimes if not is_showtime_departed(st)]
    return render_template('movies/detail.html', movie=movie, showtimes=showtimes)


@app.route('/movies/book/<int:showtime_id>', methods=['GET', 'POST'])
@login_required
def book_movie(showtime_id):
    showtime = Showtime.query.get_or_404(showtime_id)

    if is_showtime_departed(showtime):
        flash('This showtime has already started or passed. Please choose another showtime.', 'error')
        return redirect(url_for('movie_detail', movie_id=showtime.movie_id))
    
    if request.method == 'POST':
        # Compute real-time availability based on cinema capacity minus reserved bookings.
        total_seats = get_showtime_total_seats(showtime)
        reserved_seats, reserved_unknown = get_reserved_movie_seats(showtime_id, statuses=['pending', 'paid', 'completed'])
        remaining = max(0, int(total_seats) - len(reserved_seats) - int(reserved_unknown))

        try:
            num_tickets = int(request.form.get('num_tickets', 1))
        except Exception:
            num_tickets = 1
        seat_numbers = request.form.get('seat_numbers', '') or ''

        if num_tickets <= 0:
            flash('Please select at least 1 ticket.', 'error')
            return redirect(url_for('book_movie', showtime_id=showtime_id))

        # Availability check (includes pending/booking reservations)
        if num_tickets > remaining:
            flash(f'Not enough seats available. Remaining seats: {remaining}.', 'error')
            return redirect(url_for('book_movie', showtime_id=showtime_id))

        # Validate seat selection: parse and ensure count matches
        selected = [s.strip() for s in seat_numbers.split(',') if s and s.strip()]
        if len(selected) != num_tickets:
            flash(f'Please select exactly {num_tickets} seat(s).', 'error')
            return redirect(url_for('book_movie', showtime_id=showtime_id))

        # Check for duplicate seats in submission
        if len(set(selected)) != len(selected):
            flash('Duplicate seat selection detected. Please choose different seats.', 'error')
            return redirect(url_for('book_movie', showtime_id=showtime_id))

        # Validate seat labels are within cinema capacity
        invalid = [s for s in selected if not is_valid_showtime_seat_label(s, total_seats, cols=10)]
        if invalid:
            flash(f'Invalid seat selection: {", ".join(movie_seat_label_to_display(s) for s in invalid)}.', 'error')
            return redirect(url_for('book_movie', showtime_id=showtime_id))

        # Check against already reserved seats (pending/paid/completed)
        conflicts = [s for s in selected if s in reserved_seats]
        if conflicts:
            flash(
                f'The following seat(s) are no longer available: {", ".join(movie_seat_label_to_display(s) for s in conflicts)}. Please choose different seats.',
                'error'
            )
            return redirect(url_for('book_movie', showtime_id=showtime_id))
        
        total_amount = num_tickets * float(showtime.price or 0)
        booking_ref = generate_booking_reference()
        seat_numbers_normalized = ','.join(selected)
        
        booking = MovieBooking(
            user_id=current_user.id,
            showtime_id=showtime_id,
            num_tickets=num_tickets,
            seat_numbers=seat_numbers_normalized,
            total_amount=total_amount,
            booking_reference=booking_ref
        )
        db.session.add(booking)
        db.session.commit()
        
        return redirect(url_for('payment', booking_type='movie', booking_id=booking.id))
    
    total_seats = get_showtime_total_seats(showtime)
    reserved_seats, reserved_unknown = get_reserved_movie_seats(showtime_id, statuses=['pending', 'paid', 'completed'])
    remaining = max(0, int(total_seats) - len(reserved_seats) - int(reserved_unknown))
    return render_template('movies/book.html', showtime=showtime, cinema_total_seats=total_seats, seats_remaining=remaining)


# ==================== ROUTES - BUS ====================

@app.route('/bus')
@app.route('/bus/list')
def bus_routes():
    today = datetime.now().date()
    routes = BusRoute.query.filter_by(is_active=True).order_by(BusRoute.departure_time).all()
    routes = [r for r in routes if not is_route_departed_for_date(r, today)]
    return render_template('bus/list.html', routes=routes)


@app.route('/bus/search', methods=['GET', 'POST'])
def search_bus():
    if request.method == 'POST':
        origin = request.form.get('origin')
        destination = request.form.get('destination')
        selected_date = parse_travel_date(request.form.get('travel_date'))

        routes = BusRoute.query.filter(
            BusRoute.origin.ilike(f'%{origin}%'),
            BusRoute.destination.ilike(f'%{destination}%'),
            BusRoute.is_active == True
        ).order_by(BusRoute.departure_time).all()
        routes = [r for r in routes if not is_route_departed_for_date(r, selected_date)]

        return render_template('bus/search_results.html', 
                             routes=routes, 
                             origin=origin, 
                             destination=destination,
                             travel_date=selected_date.isoformat())
    
    return render_template('bus/search.html')


@app.route('/bus/book/<int:route_id>', methods=['GET', 'POST'])
@login_required
def book_bus(route_id):
    route = BusRoute.query.get_or_404(route_id)
    travel_date = request.args.get('date', datetime.now().date().isoformat())

    # Get or create schedule for the date
    parsed_date = parse_travel_date(travel_date)
    travel_date = parsed_date.isoformat()

    if is_route_departed_for_date(route, parsed_date):
        if parsed_date < datetime.now().date():
            flash('This travel date has already passed. Please choose today or a future date.', 'error')
        else:
            flash('This bus is currently in transit. It will be available again after arrival time.', 'error')
        return redirect(url_for('search_bus'))

    schedule = BusSchedule.query.filter_by(
        route_id=route_id,
        travel_date=parsed_date
    ).first()

    if not schedule:
        schedule = BusSchedule(
            route_id=route_id,
            travel_date=parsed_date,
            available_seats=route.total_seats
        )
        db.session.add(schedule)
        db.session.commit()

    total_seats = int(route.total_seats or schedule.available_seats or 0)
    reserved_seats, reserved_unknown = get_reserved_bus_seats(schedule.id, statuses=['pending', 'paid', 'completed'])
    remaining = max(0, total_seats - len(reserved_seats) - int(reserved_unknown))

    if request.method == 'POST':
        try:
            num_tickets = int(request.form.get('num_tickets', 1))
        except Exception:
            num_tickets = 1
        seat_numbers = request.form.get('seat_numbers', '') or ''
        passenger_names = request.form.get('passenger_names', '')

        if num_tickets <= 0:
            flash('Please select at least 1 passenger.', 'error')
            return redirect(url_for('book_bus', route_id=route_id, date=travel_date))

        # Availability check (includes pending/paid/completed reservations)
        if num_tickets > remaining:
            flash(f'Not enough seats available. Remaining seats: {remaining}.', 'error')
            return redirect(url_for('book_bus', route_id=route_id, date=travel_date))

        # Optional seat selection validation (if seat_numbers is provided)
        selected = [s.strip() for s in seat_numbers.split(',') if s and s.strip()]
        if seat_numbers.strip():
            if len(selected) != num_tickets:
                flash(f'Please select exactly {num_tickets} seat(s).', 'error')
                return redirect(url_for('book_bus', route_id=route_id, date=travel_date))

            if len(set(selected)) != len(selected):
                flash('Duplicate seat selection detected. Please choose different seats.', 'error')
                return redirect(url_for('book_bus', route_id=route_id, date=travel_date))

            invalid = []
            for s in selected:
                try:
                    n = int(str(s).strip())
                    if n < 1 or n > total_seats:
                        invalid.append(s)
                except Exception:
                    invalid.append(s)
            if invalid:
                flash(f'Invalid seat selection: {", ".join(invalid)}.', 'error')
                return redirect(url_for('book_bus', route_id=route_id, date=travel_date))

            conflicts = [s for s in selected if s in reserved_seats]
            if conflicts:
                flash(f'The following seat(s) are no longer available: {", ".join(conflicts)}. Please choose different seats.', 'error')
                return redirect(url_for('book_bus', route_id=route_id, date=travel_date))

        total_amount = num_tickets * route.price
        booking_ref = generate_booking_reference()
        seat_numbers_normalized = ','.join(selected) if selected else None

        booking = BusBooking(
            user_id=current_user.id,
            schedule_id=schedule.id,
            num_tickets=num_tickets,
            seat_numbers=seat_numbers_normalized,
            passenger_names=passenger_names,
            total_amount=total_amount,
            booking_reference=booking_ref
        )
        db.session.add(booking)
        db.session.commit()

        return redirect(url_for('payment', booking_type='bus', booking_id=booking.id))

    return render_template(
        'bus/book.html',
        route=route,
        schedule=schedule,
        travel_date=travel_date,
        seats_remaining=remaining
    )


# ==================== ROUTES - PAYMENT ====================

@app.route('/payment/<booking_type>/<int:booking_id>')
@login_required
def payment(booking_type, booking_id):
    booking_type = (booking_type or '').strip().lower()
    if booking_type not in ('movie', 'bus'):
        flash('Invalid booking type.', 'error')
        return redirect(url_for('index'))
    booking = get_booking_for_request(booking_type, booking_id)
    
    if booking.user_id != current_user.id:
        flash('Unauthorized access.', 'error')
        return redirect(url_for('index'))
    
    return render_template('payment/checkout.html', 
                         booking=booking, 
                         booking_type=booking_type)


@app.route('/create-checkout-session', methods=['POST'])
@app.route('/create-payment-intent', methods=['POST'])
@login_required
def create_payment_intent():
    data = request.get_json(silent=True) or {}
    booking_type = str(data.get('booking_type') or '').strip().lower()
    booking_id = data.get('booking_id')
    requested_method = data.get('payment_method', 'card')
    pm_type = normalize_checkout_payment_method(requested_method)

    if booking_type not in ('movie', 'bus'):
        return jsonify({'error': "Invalid booking_type. Expected 'movie' or 'bus'."}), 400

    try:
        booking_id = int(booking_id)
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid booking_id'}), 400

    if pm_type not in CHECKOUT_SUPPORTED_METHODS:
        return jsonify({
            'error': f"Unsupported payment method '{requested_method}' for PayMongo Checkout.",
            'supported_payment_methods': sorted(list(CHECKOUT_SUPPORTED_METHODS)),
        }), 400

    booking = get_booking_for_request(booking_type, booking_id)

    if booking.user_id != current_user.id:
        return jsonify({'error': 'Unauthorized'}), 403

    try:
        amount = int(round(float(booking.total_amount or 0) * 100))
        if amount <= 0:
            return jsonify({'error': 'Invalid booking amount'}), 400

        success_url = url_for('payment_success_page', booking_type=booking_type, booking_id=booking.id, _external=True)
        cancel_url = f"{success_url}?checkout_status=cancelled"

        payload = build_checkout_session_payload(
            amount_cents=amount,
            booking_reference=booking.booking_reference,
            success_url=success_url,
            cancel_url=cancel_url,
            payment_method_types=[pm_type],
            metadata={
                "booking_type": booking_type,
                "booking_id": str(booking.id),
                "booking_reference": booking.booking_reference,
                "selected_payment_method": pm_type,
                "requested_payment_method": str(requested_method or '').strip().lower(),
            },
            description=f"TicketHub {booking_type.title()} Booking {booking.booking_reference}",
            customer_email=getattr(current_user, 'email', None),
        )

        headers = paymongo_headers()
        if headers.get("Authorization") == "Basic MISSING_KEY":
            return jsonify({'error': 'PAYMONGO_SECRET_KEY is missing'}), 500

        resp = requests.post(
            'https://api.paymongo.com/v1/checkout_sessions',
            json=payload,
            headers=headers,
            timeout=15
        )
        try:
            resp_data = resp.json()
        except ValueError:
            return jsonify({
                'error': f'PayMongo returned invalid response (status {resp.status_code})',
                'details': resp.text[:200] if resp.text else 'Empty response'
            }), 502

        if resp.status_code not in (200, 201):
            error_msg, error_code, error_details = parse_paymongo_error(resp_data)
            return jsonify({
                'error': f'Failed to create PayMongo checkout session: {error_msg}',
                'error_code': error_code,
                'details': error_details,
            }), resp.status_code

        session_id = resp_data.get('data', {}).get('id')
        attrs = resp_data.get('data', {}).get('attributes', {})
        checkout_url = attrs.get('checkout_url') if isinstance(attrs, dict) else None

        if not checkout_url or not session_id:
            return jsonify({'error': 'PayMongo did not return a valid checkout session.'}), 502

        booking.payment_method = pm_type
        booking.payment_reference = session_id
        booking.payment_status = 'pending'
        db.session.commit()

        return jsonify({
            'checkout_url': checkout_url,
            'checkout_session_id': session_id,
            'payment_method': pm_type,
        })
    except requests.RequestException as e:
        return jsonify({'error': 'Failed to create PayMongo checkout session', 'details': str(e)}), 502
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/confirm-gcash-payment', methods=['POST'])
@login_required
def confirm_gcash_payment():
    """Confirm a GCash payment by checking PayMongo for a completed payment linked to the source or booking."""
    data = request.get_json() or {}
    booking_type = str(data.get('booking_type') or '').strip().lower()
    booking_id = data.get('booking_id')
    source_id = data.get('source_id')

    if booking_type not in ('movie', 'bus'):
        return jsonify({'success': False, 'error': "Invalid booking type"}), 400

    booking = get_booking_for_request(booking_type, booking_id)

    if booking.user_id != current_user.id:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403

    # If booking already paid, return success
    if booking.payment_status == 'paid':
        return jsonify({'success': True, 'message': 'Already marked paid'})

    # Try to find a PayMongo payment for the source_id or booking reference
    try:
        payments = pm_list_payments(limit=100)
        found = None
        if isinstance(payments, dict) and payments.get('data'):
            for p in payments.get('data', []):
                attrs = p.get('attributes', {})
                # Check nested source id
                src = attrs.get('source') or {}
                src_id = None
                if isinstance(src, dict):
                    src_id = src.get('id')
                # Check metadata
                meta = attrs.get('metadata') or {}

                if source_id and src_id == source_id:
                    found = p
                    break
                if meta and meta.get('booking_reference') == booking.booking_reference:
                    found = p
                    break

        if not found:
            return jsonify({'success': False, 'error': 'Payment not found or not completed yet'}), 404

        status = found.get('attributes', {}).get('status')
        payment_id = found.get('id') or found.get('data', {}).get('id')

        # Consider these statuses as successful/completed
        if status and status.lower() in ('succeeded', 'paid', 'captured', 'completed'):
            mark_booking_paid(
                booking,
                booking_type=booking_type,
                payment_method='gcash',
                payment_reference=payment_id or source_id or booking.payment_reference,
                completed_by=current_user.id
            )

            return jsonify({'success': True, 'message': 'Payment confirmed'})
        else:
            return jsonify({'success': False, 'error': f'Payment status: {status}'}), 400

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# Removed duplicate route - using payment_success_page instead (below)


@app.route('/payment-bank-pending', methods=['POST'])
@login_required
def payment_bank_pending():
    data = request.get_json()
    booking_type = data.get('booking_type')
    booking_id = data.get('booking_id')

    if booking_type == 'movie':
        booking = MovieBooking.query.get_or_404(booking_id)
    else:
        booking = BusBooking.query.get_or_404(booking_id)

    if booking.user_id != current_user.id:
        return jsonify({'error': 'Unauthorized'}), 403

    # Generate a bank reference
    bank_ref = f'BANK-{booking_id}-{int(datetime.now().timestamp())}'

    # Mark as pending bank transfer and store method/reference
    booking.payment_status = 'pending'
    booking.payment_method = 'bank'
    booking.payment_reference = bank_ref

    db.session.commit()

    flash('Bank transfer recorded. Your booking will be confirmed once payment is verified.', 'info')

    return jsonify({'success': True, 'reference_number': bank_ref})


@app.route('/get-booked-seats', methods=['POST'])
def get_booked_seats():
    data = request.get_json()
    showtime_id = data.get('showtime_id')
    
    # Consider any booking that is pending, paid or completed as reserved for seat selection
    booked_seats = []
    try:
        reserved, _unknown = get_reserved_movie_seats(showtime_id, statuses=['pending', 'paid', 'completed'])
        booked_seats = sorted(list(reserved))
    except Exception as e:
        print(f"[Seats] Error fetching booked seats: {e}")

    return jsonify({'booked_seats': booked_seats})


@app.route('/api/showtime-seats/<int:showtime_id>', methods=['GET'])
def api_showtime_seats(showtime_id):
    """Return seat layout, booked seats and available seats for a showtime.

    Response:
    {
      "showtime_id": 1,
      "cinema_total_seats": 100,
      "cols": 10,
      "rows": 10,
      "booked_seats": ["1-1","1-2"],
      "available_seats": ["1-3",...],
      "available_count": 98
    }
    """
    showtime = Showtime.query.get_or_404(showtime_id)
    # Use cinema total seats if available, otherwise fallback to showtime.available_seats
    cinema_total = None
    try:
        cinema_total = showtime.cinema.total_seats if showtime.cinema and showtime.cinema.total_seats else None
    except Exception:
        cinema_total = None

    total_seats = int(cinema_total or (showtime.available_seats or 0))
    # Default layout: 10 columns
    cols = 10
    import math
    rows = math.ceil(total_seats / cols) if total_seats > 0 else 1

    # Gather reserved seats (pending/paid/completed)
    booked = []
    try:
        reserved, _unknown = get_reserved_movie_seats(showtime_id, statuses=['pending', 'paid', 'completed'])
        booked = list(reserved)
    except Exception as e:
        print(f"[API] Error collecting booked seats for showtime {showtime_id}: {e}")

    # Generate full seat list using row-col labels 'r-c'
    all_seats = []
    for r in range(1, rows + 1):
        for c in range(1, cols + 1):
            label = f"{r}-{c}"
            all_seats.append(label)
            if len(all_seats) >= total_seats:
                break
        if len(all_seats) >= total_seats:
            break

    booked_set = set(booked)
    available = [s for s in all_seats if s not in booked_set]

    return jsonify({
        'showtime_id': showtime_id,
        'cinema_total_seats': total_seats,
        'cols': cols,
        'rows': rows,
        'booked_seats': sorted(list(booked_set)),
        'available_seats': available,
        'available_count': len(available)
    }), 200


@app.route('/api/schedule-seats/<int:schedule_id>', methods=['GET'])
def api_schedule_seats(schedule_id):
    """Return bus schedule seat availability. Seats are numbered 1..N (route.total_seats).

    Response:
    {
      "schedule_id": 1,
      "total_seats": 40,
      "booked_seats": ["1","2"],
      "available_seats": ["3",...],
      "available_count": 38
    }
    """
    schedule = BusSchedule.query.get_or_404(schedule_id)
    route = schedule.route
    total = int(route.total_seats or schedule.available_seats or 0)

    # Gather reserved seats
    reserved_statuses = ['pending', 'paid', 'completed']
    booked = []
    unknown_reserved = 0
    try:
        reserved, unknown_reserved = get_reserved_bus_seats(schedule_id, statuses=reserved_statuses)
        booked = list(reserved)
    except Exception as e:
        print(f"[API] Error collecting booked seats for schedule {schedule_id}: {e}")

    all_seats = [str(i) for i in range(1, total + 1)]
    booked_set = set(booked)
    available = [s for s in all_seats if s not in booked_set]
    available_count = max(0, total - len(booked_set) - int(unknown_reserved))

    return jsonify({
        'schedule_id': schedule_id,
        'total_seats': total,
        'booked_seats': sorted(list(booked_set), key=lambda x: int(x) if x.isdigit() else x),
        'available_seats': available,
        'available_count': available_count,
        'unknown_reserved_count': int(unknown_reserved or 0)
    }), 200


@app.route('/get-booked-bus-seats', methods=['POST'])
def get_booked_bus_seats():
    data = request.get_json()
    schedule_id = data.get('schedule_id')

    # Consider any booking that is pending, paid or completed as reserved for seat selection
    booked_seats = []
    try:
        reserved, _unknown = get_reserved_bus_seats(schedule_id, statuses=['pending', 'paid', 'completed'])
        booked_seats = sorted(list(reserved), key=lambda x: int(x) if str(x).isdigit() else str(x))
    except Exception as e:
        print(f"[Bus Seats] Error fetching booked seats: {e}")

    return jsonify({'booked_seats': booked_seats})

@app.route('/payment-ewallet-pending', methods=['GET', 'POST'])
@login_required
def payment_ewallet_pending():
    if request.method == 'POST':
        data = request.get_json(silent=True) or request.form.to_dict()
    else:
        data = request.args.to_dict()

    booking_type = (data.get("booking_type") or "").strip().lower()
    booking_id_raw = data.get("booking_id")
    payment_method = (data.get("payment_method") or "").strip()
    redirect_mode = str(data.get("redirect", "")).strip().lower() in ("1", "true", "yes")

    def respond_error(message, status_code=400, error_code=None, details=None):
        if redirect_mode:
            flash(message, 'error')
            try:
                if booking_type and booking_id_raw:
                    return redirect(url_for('payment', booking_type=booking_type, booking_id=int(booking_id_raw)))
            except Exception:
                pass
            return redirect(url_for('index'))

        error_response = {"success": False, "error": message}
        if error_code:
            error_response["error_code"] = error_code
        if details:
            error_response["details"] = details
        return jsonify(error_response), status_code

    # Validate required fields
    if not all([booking_type, booking_id_raw, payment_method]):
        return respond_error("Missing required fields: booking_type, booking_id, payment_method", 400)

    try:
        booking_id = int(booking_id_raw)
    except (TypeError, ValueError):
        return respond_error("Invalid booking id", 400)

    if booking_type not in ('movie', 'bus'):
        return respond_error("Invalid booking type. Expected 'movie' or 'bus'.", 400)

    # Get booking
    try:
        booking = get_booking_for_request(booking_type, booking_id)
    except Exception as e:
        return respond_error(f"Booking not found: {str(e)}", 404)

    if booking.user_id != current_user.id:
        return respond_error("Unauthorized access.", 403)

    # Normalize payment method to PayMongo Checkout Session types.
    requested_pm_type = payment_method.lower().strip()
    pm_type = normalize_checkout_payment_method(requested_pm_type)

    if pm_type not in CHECKOUT_SUPPORTED_METHODS:
        valid_types = ", ".join(sorted(CHECKOUT_SUPPORTED_METHODS))
        return respond_error(f"Invalid payment method: {requested_pm_type}. Valid types: {valid_types}", 400)

    try:
        amount = int(round(float(booking.total_amount or 0) * 100))
        if amount <= 0:
            return respond_error("Invalid booking amount", 400)

        success_url = url_for('payment_success_page', booking_type=booking_type, booking_id=booking.id, _external=True)
        cancel_url = f"{success_url}?checkout_status=cancelled"

        payload = build_checkout_session_payload(
            amount_cents=amount,
            booking_reference=booking.booking_reference,
            success_url=success_url,
            cancel_url=cancel_url,
            payment_method_types=[pm_type],
            metadata={
                "booking_type": booking_type,
                "booking_id": str(booking.id),
                "booking_reference": booking.booking_reference,
                "selected_payment_method": pm_type,
                "requested_payment_method": requested_pm_type,
            },
            description=f"TicketHub {booking_type.title()} Booking {booking.booking_reference}",
            customer_email=getattr(current_user, 'email', None),
        )

        print(f"\n[PayMongo] ========== REQUEST ==========")
        print(f"[PayMongo] Endpoint: POST https://api.paymongo.com/v1/checkout_sessions")
        print(f"[PayMongo] Payment Type: {pm_type}")
        print(f"[PayMongo] Amount: {amount} centavos (P{booking.total_amount})")
        print(f"[PayMongo] Booking: {booking_type} #{booking_id}")

        headers = paymongo_headers()
        print(f"[PayMongo] Auth Header: {headers.get('Authorization', 'MISSING')[:20]}...")
        print(f"[PayMongo] Payload: {payload}\n")

        if headers.get("Authorization") == "Basic MISSING_KEY":
            return respond_error("PayMongo secret key is missing. Set PAYMONGO_SECRET_KEY in .env.", 500)

        resp = requests.post(
            'https://api.paymongo.com/v1/checkout_sessions',
            json=payload,
            headers=headers,
            timeout=15
        )

        print(f"[PayMongo] ========== RESPONSE ==========")
        print(f"[PayMongo] Status Code: {resp.status_code}")
        print(f"[PayMongo] Content-Type: {resp.headers.get('content-type', 'unknown')}")

        # Try to parse JSON, but handle cases where response is not JSON
        try:
            resp_data = resp.json()
            print(f"[PayMongo] Response Body (JSON): {resp_data}")
        except ValueError as je:
            print(f"[PayMongo] Failed to parse JSON: {str(je)}")
            print(f"[PayMongo] Raw Response Text: {resp.text[:500]}")
            return respond_error(
                f"PayMongo returned invalid response (status {resp.status_code})",
                500,
                details=resp.text[:200] if resp.text else "Empty response"
            )

        if resp.status_code not in (200, 201):
            error_msg, error_code, error_details = parse_paymongo_error(resp_data)
            print(f"[PayMongo] ERROR - Code: {error_code}, Message: {error_msg}\n")
            return respond_error(
                f"PayMongo request failed: {error_msg}",
                resp.status_code,
                error_code=error_code,
                details=error_details if error_details else (resp.text[:200] if resp.text else None)
            )

        checkout_session_id = resp_data.get('data', {}).get('id')
        attrs = resp_data.get('data', {}).get('attributes', {})
        checkout_url = attrs.get('checkout_url') if isinstance(attrs, dict) else None

        print(f"[PayMongo] SUCCESS")
        print(f"[PayMongo] Checkout Session ID: {checkout_session_id}")
        print(f"[PayMongo] Checkout URL: {checkout_url}\n")

        if not checkout_url:
            return respond_error("PayMongo did not return a checkout URL. Please try again.", 502)

        # Mark booking as pending and store reference
        booking.payment_status = 'pending'
        booking.payment_method = pm_type
        booking.payment_reference = checkout_session_id

        # Log the payment transaction
        log_payment_transaction(
            user_id=current_user.id,
            booking_type=booking_type,
            booking_id=booking_id,
            booking_ref=booking.booking_reference,
            amount=booking.total_amount,
            payment_method=pm_type,
            status='pending',
            source_id=checkout_session_id
        )
        db.session.commit()

        if redirect_mode:
            return redirect(checkout_url)

        return jsonify({
            "success": True,
            "checkout_url": checkout_url,
            "booking_id": booking.id,
            "booking_type": booking_type,
            "checkout_session_id": checkout_session_id
        })
    except requests.exceptions.Timeout:
        print(f"[PayMongo] TIMEOUT - Request took longer than 15 seconds\n")
        return respond_error("PayMongo request timed out. Please try again.", 500)
    except requests.exceptions.ConnectionError as e:
        print(f"[PayMongo] CONNECTION ERROR: {str(e)}\n")
        return respond_error(f"Failed to connect to PayMongo: {str(e)}", 500)
    except requests.RequestException as e:
        print(f"[PayMongo] REQUEST ERROR: {str(e)}\n")
        return respond_error(f"PayMongo request failed: {str(e)}", 500)
    except Exception as e:
        print(f"[PayMongo] UNEXPECTED ERROR: {str(e)}\n")
        import traceback
        traceback.print_exc()
        return respond_error(f"Server error: {str(e)}", 500)


# ----------------------
# E-wallet Payment Success Redirect
# ----------------------
@app.route('/payment-success/<booking_type>/<int:booking_id>')
@login_required
def payment_success_page(booking_type, booking_id):
    booking_type = (booking_type or '').strip().lower()
    if booking_type not in ('movie', 'bus'):
        flash('Invalid booking type.', 'error')
        return redirect(url_for('index'))

    booking = get_booking_for_request(booking_type, booking_id)

    if booking.user_id != current_user.id and not current_user.is_admin:
        flash('Unauthorized access.', 'error')
        return redirect(url_for('index'))

    checkout_status = str(request.args.get('checkout_status') or '').strip().lower()
    if checkout_status in ('cancelled', 'failed'):
        if str(booking.payment_status or '').lower() not in ('paid', 'completed'):
            booking.payment_status = 'failed'
            db.session.commit()
        flash('Payment was not completed. You can retry checkout from your booking page.', 'warning')
        return render_template("payment/payment_pending.html", booking=booking, booking_type=booking_type)

    already_paid = str(booking.payment_status or '').strip().lower() in ('paid', 'completed')
    if not already_paid:
        query_session_id = (
            request.args.get('checkout_session_id')
            or request.args.get('session_id')
            or request.args.get('id')
        )
        booking_ref = str(booking.payment_reference or '').strip()
        checkout_session_id = query_session_id or (booking_ref if booking_ref.startswith('cs_') else None)

        if not checkout_session_id:
            flash('Payment is still pending confirmation. Please try again shortly.', 'info')
            return render_template("payment/payment_pending.html", booking=booking, booking_type=booking_type)

        checkout_data = pm_retrieve_checkout_session(checkout_session_id)
        if checkout_data.get('error'):
            print(f"[PayMongo] Checkout verification failed for {checkout_session_id}: {checkout_data.get('error')}")
            flash('Payment verification is still in progress. Please try again in a moment.', 'info')
            return render_template("payment/payment_pending.html", booking=booking, booking_type=booking_type)

        attrs = (checkout_data.get('data') or {}).get('attributes') if isinstance(checkout_data.get('data'), dict) else {}
        metadata = attrs.get('metadata') if isinstance(attrs, dict) else {}
        if isinstance(metadata, dict):
            meta_type = str(metadata.get('booking_type') or '').strip().lower()
            meta_id = str(metadata.get('booking_id') or '').strip()
            if (meta_type and meta_type != booking_type) or (meta_id and meta_id != str(booking.id)):
                flash('Payment verification mismatch. Please contact support.', 'error')
                return render_template("payment/payment_pending.html", booking=booking, booking_type=booking_type)

        if not checkout_session_is_paid(checkout_data):
            flash('Payment is still pending confirmation. Please try again shortly.', 'info')
            return render_template("payment/payment_pending.html", booking=booking, booking_type=booking_type)

        confirmed_payment_ref = checkout_session_id
        if isinstance(attrs, dict):
            payments = attrs.get('payments')
            if isinstance(payments, list) and payments:
                first_payment = payments[0]
                if isinstance(first_payment, str) and first_payment.strip():
                    confirmed_payment_ref = first_payment.strip()
                elif isinstance(first_payment, dict):
                    confirmed_payment_ref = first_payment.get('id') or confirmed_payment_ref

        mark_booking_paid(
            booking,
            booking_type=booking_type,
            payment_method=booking.payment_method or 'card',
            payment_reference=confirmed_payment_ref,
            completed_by=current_user.id
        )

    return render_template(
        "payment/success.html",
        booking=booking,
        booking_type=booking_type,
        qr_ticket=get_qr_ticket_context(booking_type, booking)
    )


@app.route('/ticket/scan/<token>')
def scan_ticket_qr(token):
    """Scan endpoint used by booking QR codes."""
    error_message = None
    booking = None
    booking_type = None
    ticket_valid = False
    just_verified = False

    try:
        payload = serializer.loads(token, salt='ticket-qr-salt', max_age=60 * 60 * 24 * 365 * 10)
        booking_type = str(payload.get('booking_type') or '').strip().lower()
        booking_id = payload.get('booking_id')
        booking_ref = str(payload.get('booking_reference') or '').strip()

        if booking_type not in ('movie', 'bus'):
            raise BadSignature('Invalid booking type in token.')

        booking = get_booking_or_none(booking_type, booking_id)
        if not booking:
            error_message = 'Booking record was not found.'
        elif str(getattr(booking, 'booking_reference', '') or '').strip() != booking_ref:
            error_message = 'Booking reference mismatch.'
        elif not is_booking_paid(booking):
            error_message = 'Booking exists but payment is not completed.'
        else:
            ticket_valid = True
            if hasattr(booking, 'is_verified') and not bool(booking.is_verified):
                booking.is_verified = True
                booking.verified_at = datetime.now()
                db.session.commit()
                just_verified = True
                try:
                    send_booking_verified_email(booking.user, booking_type, booking, verified_at=booking.verified_at)
                except Exception as notify_err:
                    print(f"[Email] Could not send verification follow-up email: {str(notify_err)}")
    except SignatureExpired:
        error_message = 'This ticket QR has expired.'
    except BadSignature:
        error_message = 'Invalid QR code signature.'
    except Exception as e:
        error_message = f'Unable to verify QR code: {str(e)}'

    return render_template(
        'payment/ticket_verify.html',
        ticket_valid=ticket_valid,
        booking=booking,
        booking_type=booking_type,
        error_message=error_message,
        scanned_at=datetime.now(),
        just_verified=just_verified
    )

# ----------------------
# PayMongo Webhook (Optional if using dynamic intents)
# ----------------------
@app.route('/webhook/paymongo', methods=['POST'])
def paymongo_webhook():
    payload = request.get_json(silent=True) or {}

    event_type = ''
    metadata = {}
    resource_id = None
    paid_payment_id = None

    try:
        data = payload.get('data') if isinstance(payload, dict) else {}
        data = data if isinstance(data, dict) else {}
        event_attributes = data.get('attributes') if isinstance(data.get('attributes'), dict) else {}
        event_type = str(event_attributes.get('type') or '').strip().lower()

        resource = event_attributes.get('data') if isinstance(event_attributes.get('data'), dict) else {}
        resource_attributes = resource.get('attributes') if isinstance(resource.get('attributes'), dict) else {}

        metadata = resource_attributes.get('metadata') or event_attributes.get('metadata') or {}
        if not isinstance(metadata, dict):
            metadata = {}

        resource_id = resource.get('id') or data.get('id') or payload.get('id')

        payments = resource_attributes.get('payments')
        if isinstance(payments, list) and payments:
            first_payment = payments[0]
            if isinstance(first_payment, str) and first_payment.strip():
                paid_payment_id = first_payment.strip()
            elif isinstance(first_payment, dict):
                paid_payment_id = first_payment.get('id')
    except Exception:
        pass

    booking, booking_type = find_booking_from_metadata(metadata=metadata, payment_reference=resource_id)
    if not booking:
        return jsonify({"success": True, "ignored": "booking_not_found"}), 200

    booking_type = booking_type or infer_booking_type(booking) or 'movie'
    selected_method = normalize_checkout_payment_method(
        (metadata.get('selected_payment_method') or metadata.get('requested_payment_method') or booking.payment_method or 'card')
    ) or (booking.payment_method or 'card')

    if event_type and ("paid" in event_type or "succeeded" in event_type):
        mark_booking_paid(
            booking,
            booking_type=booking_type,
            payment_method=selected_method,
            payment_reference=paid_payment_id or resource_id,
            completed_by=None
        )
    elif event_type and ("failed" in event_type or "cancelled" in event_type):
        if str(booking.payment_status or '').strip().lower() not in ('paid', 'completed'):
            booking.payment_status = 'failed'
            if resource_id:
                booking.payment_reference = resource_id
            db.session.commit()

    return jsonify({"success": True}), 200

@app.route('/check-ewallet-payment/<booking_type>/<int:booking_id>')
@login_required
def check_ewallet_payment(booking_type, booking_id):
    booking_type = (booking_type or '').strip().lower()
    if booking_type not in ('movie', 'bus'):
        return jsonify({'error': 'Invalid booking type'}), 400

    booking = get_booking_for_request(booking_type, booking_id)
    if booking.user_id != current_user.id and not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403

    return jsonify({"paid": str(booking.payment_status or '').strip().lower() in ('paid', 'completed')})


# ==================== ROUTES - PayMongo API Endpoints ====================

# --- Payment Intent Endpoints ---
@app.route('/api/payment-intents', methods=['POST'])
@login_required
def api_create_payment_intent():
    """Create a PayMongo Payment Intent"""
    data = request.get_json() or {}
    amount = data.get('amount')  # in cents
    currency = data.get('currency', 'PHP')
    metadata = data.get('metadata', {})
    description = data.get('description')
    
    if not amount:
        return jsonify({"error": "amount is required"}), 400
    
    result = pm_create_payment_intent(int(amount), currency, metadata, description)
    return jsonify(result), 200 if 'data' in result else 400

@app.route('/api/payment-intents/<intent_id>', methods=['GET'])
@login_required
def api_get_payment_intent(intent_id):
    """Retrieve a PayMongo Payment Intent"""
    result = pm_retrieve_payment_intent(intent_id)
    return jsonify(result), 200 if 'data' in result else 400

@app.route('/api/payment-intents/<intent_id>/attach', methods=['POST'])
@login_required
def api_attach_payment_method(intent_id):
    """Attach a payment method to a payment intent"""
    data = request.get_json() or {}
    payment_method_id = data.get('payment_method_id')
    
    if not payment_method_id:
        return jsonify({"error": "payment_method_id is required"}), 400
    
    result = pm_attach_payment_method_to_intent(intent_id, payment_method_id)
    return jsonify(result), 200 if 'data' in result else 400

# --- Payment Method Endpoints ---
@app.route('/api/payment-methods', methods=['POST'])
@login_required
def api_create_payment_method():
    """Create a PayMongo Payment Method"""
    data = request.get_json() or {}
    type_name = data.get('type')
    details = data.get('details', {})
    
    if not type_name:
        return jsonify({"error": "type is required"}), 400
    
    result = pm_create_payment_method(type_name, details)
    return jsonify(result), 200 if 'data' in result else 400

@app.route('/api/payment-methods/<method_id>', methods=['GET'])
@login_required
def api_get_payment_method(method_id):
    """Retrieve a PayMongo Payment Method"""
    result = pm_retrieve_payment_method(method_id)
    return jsonify(result), 200 if 'data' in result else 400

@app.route('/api/payment-methods/<method_id>', methods=['POST'])
@login_required
def api_update_payment_method(method_id):
    """Update a PayMongo Payment Method"""
    data = request.get_json() or {}
    metadata = data.get('metadata')
    
    result = pm_update_payment_method(method_id, metadata)
    return jsonify(result), 200 if 'data' in result else 400

# --- Payment Endpoints ---
@app.route('/api/payments/<payment_id>', methods=['GET'])
@login_required
def api_get_payment(payment_id):
    """Retrieve a PayMongo Payment"""
    result = pm_retrieve_payment(payment_id)
    return jsonify(result), 200 if 'data' in result else 400

@app.route('/api/payments', methods=['GET'])
@login_required
@admin_required
def api_list_payments():
    """List all PayMongo Payments"""
    limit = request.args.get('limit', 20, type=int)
    after = request.args.get('after')
    
    result = pm_list_payments(limit, after)
    return jsonify(result), 200 if 'data' in result else 400

# --- Refund Endpoints ---
@app.route('/api/refunds', methods=['POST'])
@login_required
@admin_required
def api_create_refund():
    """Create a PayMongo Refund"""
    data = request.get_json() or {}
    payment_id = data.get('payment_id')
    amount = data.get('amount')
    reason = data.get('reason')
    notes = data.get('notes')
    
    if not payment_id:
        return jsonify({"error": "payment_id is required"}), 400
    
    result = pm_create_refund(payment_id, amount, reason, notes)
    return jsonify(result), 200 if 'data' in result else 400

@app.route('/api/refunds/<refund_id>', methods=['GET'])
@login_required
@admin_required
def api_get_refund(refund_id):
    """Retrieve a PayMongo Refund"""
    result = pm_retrieve_refund(refund_id)
    return jsonify(result), 200 if 'data' in result else 400

@app.route('/api/refunds', methods=['GET'])
@login_required
@admin_required
def api_list_refunds():
    """List all PayMongo Refunds"""
    limit = request.args.get('limit', 20, type=int)
    after = request.args.get('after')
    
    result = pm_list_refunds(limit, after)
    return jsonify(result), 200 if 'data' in result else 400

# --- Customer Endpoints ---
@app.route('/api/customers', methods=['POST'])
@login_required
def api_create_customer():
    """Create a PayMongo Customer"""
    data = request.get_json() or {}
    email = data.get('email')
    phone = data.get('phone')
    first_name = data.get('first_name')
    last_name = data.get('last_name')
    metadata = data.get('metadata')
    
    if not email:
        return jsonify({"error": "email is required"}), 400
    
    result = pm_create_customer(email, phone, first_name, last_name, metadata)
    return jsonify(result), 200 if 'data' in result else 400

@app.route('/api/customers/<customer_id>', methods=['GET'])
@login_required
def api_get_customer(customer_id):
    """Retrieve a PayMongo Customer"""
    result = pm_retrieve_customer(customer_id)
    return jsonify(result), 200 if 'data' in result else 400

@app.route('/api/customers/<customer_id>', methods=['POST'])
@login_required
def api_update_customer(customer_id):
    """Update a PayMongo Customer"""
    data = request.get_json() or {}
    email = data.get('email')
    phone = data.get('phone')
    first_name = data.get('first_name')
    last_name = data.get('last_name')
    metadata = data.get('metadata')
    
    result = pm_update_customer(customer_id, email, phone, first_name, last_name, metadata)
    return jsonify(result), 200 if 'data' in result else 400

@app.route('/api/customers', methods=['GET'])
@login_required
@admin_required
def api_list_customers():
    """List all PayMongo Customers"""
    limit = request.args.get('limit', 20, type=int)
    after = request.args.get('after')
    
    result = pm_list_customers(limit, after)
    return jsonify(result), 200 if 'data' in result else 400


# ======================== DIAGNOSTICS ========================

@app.route('/api/test-paymongo', methods=['GET'])
@login_required
@admin_required
def test_paymongo():
    """Test PayMongo connection and credentials"""
    print("\n[Diagnostics] Testing PayMongo connection...\n")
    
    secret_key = (
        os.environ.get("PAYMONGO_SECRET_KEY")
        or os.environ.get("PAYMONGO_API_KEY")
        or os.environ.get("PAYMOONGO_API_KEY")
    )
    public_key = os.environ.get("PAYMONGO_PUBLIC_KEY")
    
    result = {
        "timestamp": datetime.utcnow().isoformat(),
        "secret_key_set": bool(secret_key),
        "public_key_set": bool(public_key),
        "tests": {}
    }
    
    if secret_key:
        result["secret_key_preview"] = f"{secret_key[:10]}...{secret_key[-5:]}"
    
    if public_key:
        result["public_key_preview"] = f"{public_key[:10]}...{public_key[-5:]}"
    
    # Test 1: List payments (basic auth test)
    print("[Diagnostics] Test 1: Listing PayMongo payments...")
    try:
        resp = requests.get(
            'https://api.paymongo.com/v1/payments',
            headers=paymongo_headers(),
            timeout=10,
            params={"limit": 1}
        )
        result["tests"]["list_payments"] = {
            "status": resp.status_code,
            "success": resp.status_code == 200,
            "message": "✓ Authentication successful" if resp.status_code == 200 else f"✗ HTTP {resp.status_code}"
        }
        print(f"[Diagnostics] Status: {resp.status_code} - {result['tests']['list_payments']['message']}")
    except Exception as e:
        result["tests"]["list_payments"] = {
            "success": False,
            "error": str(e),
            "message": f"✗ Request failed: {str(e)}"
        }
        print(f"[Diagnostics] Error: {str(e)}")
    
    # Test 2: Create test source (card method)
    print("[Diagnostics] Test 2: Creating test card source...")
    try:
        payload = {
            "data": {
                "attributes": {
                    "amount": 10000,  # ₱100
                    "currency": "PHP",
                    "type": "card",
                    "redirect": {
                        "success": "https://example.com/success",
                        "failed": "https://example.com/failed"
                    }
                }
            }
        }
        resp = requests.post(
            'https://api.paymongo.com/v1/sources',
            json=payload,
            headers=paymongo_headers(),
            timeout=10
        )
        try:
            resp_data = resp.json()
        except ValueError:
            resp_data = {}
        error_msg, _, _ = parse_paymongo_error(resp_data) if resp.status_code not in (200, 201) else (None, None, None)
        result["tests"]["create_card_source"] = {
            "status": resp.status_code,
            "success": resp.status_code in (200, 201),
            "message": "✓ Card source created" if resp.status_code in (200, 201) else f"✗ HTTP {resp.status_code}",
            "error": error_msg
        }
        print(f"[Diagnostics] Status: {resp.status_code} - {result['tests']['create_card_source']['message']}")
    except Exception as e:
        result["tests"]["create_card_source"] = {
            "success": False,
            "error": str(e),
            "message": f"✗ Request failed: {str(e)}"
        }
        print(f"[Diagnostics] Error: {str(e)}")
    
    # Test 3: Create test source (gcash method)
    print("[Diagnostics] Test 3: Creating test GCash source...")
    try:
        payload = {
            "data": {
                "attributes": {
                    "amount": 10000,
                    "currency": "PHP",
                    "type": "gcash",
                    "redirect": {
                        "success": "https://example.com/success",
                        "failed": "https://example.com/failed"
                    }
                }
            }
        }
        resp = requests.post(
            'https://api.paymongo.com/v1/sources',
            json=payload,
            headers=paymongo_headers(),
            timeout=10
        )
        try:
            resp_data = resp.json()
        except ValueError:
            resp_data = {}
        error_msg, _, _ = parse_paymongo_error(resp_data) if resp.status_code not in (200, 201) else (None, None, None)
        result["tests"]["create_gcash_source"] = {
            "status": resp.status_code,
            "success": resp.status_code in (200, 201),
            "message": "✓ GCash source created" if resp.status_code in (200, 201) else f"✗ HTTP {resp.status_code}",
            "error": error_msg
        }
        print(f"[Diagnostics] Status: {resp.status_code} - {result['tests']['create_gcash_source']['message']}")
    except Exception as e:
        result["tests"]["create_gcash_source"] = {
            "success": False,
            "error": str(e),
            "message": f"✗ Request failed: {str(e)}"
        }
        print(f"[Diagnostics] Error: {str(e)}")
    
    # Test 4: Create test source (paymaya method)
    print("[Diagnostics] Test 4: Creating test PayMaya source...")
    try:
        payload = {
            "data": {
                "attributes": {
                    "amount": 10000,
                    "currency": "PHP",
                    "type": "paymaya",
                    "redirect": {
                        "success": "https://example.com/success",
                        "failed": "https://example.com/failed"
                    }
                }
            }
        }
        resp = requests.post(
            'https://api.paymongo.com/v1/sources',
            json=payload,
            headers=paymongo_headers(),
            timeout=10
        )
        try:
            resp_data = resp.json()
        except ValueError:
            resp_data = {}
        error_msg, _, _ = parse_paymongo_error(resp_data) if resp.status_code not in (200, 201) else (None, None, None)
        result["tests"]["create_paymaya_source"] = {
            "status": resp.status_code,
            "success": resp.status_code in (200, 201),
            "message": "✓ PayMaya source created" if resp.status_code in (200, 201) else f"✗ HTTP {resp.status_code}",
            "error": error_msg
        }
        print(f"[Diagnostics] Status: {resp.status_code} - {result['tests']['create_paymaya_source']['message']}")
    except Exception as e:
        result["tests"]["create_paymaya_source"] = {
            "success": False,
            "error": str(e),
            "message": f"✗ Request failed: {str(e)}"
        }
        print(f"[Diagnostics] Error: {str(e)}")
    
    print("\n[Diagnostics] Testing complete.\n")
    
    return jsonify(result), 200


# ======================== END DIAGNOSTICS ========================
@app.route('/api/transactions', methods=['GET'])
@login_required
@admin_required
def api_list_transactions():
    """List all payment transactions (admin only)"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    user_id = request.args.get('user_id', type=int)
    booking_type = request.args.get('booking_type')
    status = request.args.get('status')
    
    query = PaymentTransaction.query
    
    if user_id:
        query = query.filter_by(user_id=user_id)
    if booking_type:
        query = query.filter_by(booking_type=booking_type)
    if status:
        query = query.filter_by(payment_status=status)
    
    paginated = query.order_by(PaymentTransaction.created_at.desc()).paginate(page=page, per_page=per_page)
    
    transactions = [{
        'id': t.id,
        'user_id': t.user_id,
        'booking_type': t.booking_type,
        'booking_reference': t.booking_reference,
        'amount': t.amount,
        'payment_method': t.payment_method,
        'payment_status': t.payment_status,
        'source_id': t.payment_source_id,
        'completed_by': t.completed_by,
        'completed_by_name': getattr(t.completed_by_user, 'name', None) if t.completed_by_user else None,
        'created_at': t.created_at.isoformat(),
        'updated_at': t.updated_at.isoformat()
    } for t in paginated.items]
    
    return jsonify({
        'transactions': transactions,
        'total': paginated.total,
        'pages': paginated.pages,
        'current_page': page
    }), 200

@app.route('/api/transactions/<int:transaction_id>', methods=['GET'])
@login_required
@admin_required
def api_get_transaction(transaction_id):
    """Get a specific transaction"""
    transaction = PaymentTransaction.query.get_or_404(transaction_id)
    
    return jsonify({
        'id': transaction.id,
        'user_id': transaction.user_id,
        'booking_type': transaction.booking_type,
        'booking_id': transaction.booking_id,
        'booking_reference': transaction.booking_reference,
        'amount': transaction.amount,
        'currency': transaction.currency,
        'payment_method': transaction.payment_method,
        'payment_status': transaction.payment_status,
        'source_id': transaction.payment_source_id,
        'completed_by': transaction.completed_by,
        'completed_by_name': getattr(transaction.completed_by_user, 'name', None) if transaction.completed_by_user else None,
        'created_at': transaction.created_at.isoformat(),
        'updated_at': transaction.updated_at.isoformat()
    }), 200

@app.route('/api/transactions/user/<int:user_id>', methods=['GET'])
@login_required
def api_get_user_transactions(user_id):
    """Get all transactions for a user (user can only see their own)"""
    # Users can only view their own transactions
    if current_user.id != user_id and not current_user.is_admin:
        return jsonify({"error": "Unauthorized"}), 403
    
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    
    paginated = PaymentTransaction.query.filter_by(user_id=user_id).order_by(PaymentTransaction.created_at.desc()).paginate(page=page, per_page=per_page)
    
    transactions = [{
        'id': t.id,
        'booking_type': t.booking_type,
        'booking_reference': t.booking_reference,
        'amount': t.amount,
        'payment_method': t.payment_method,
        'payment_status': t.payment_status,
        'created_at': t.created_at.isoformat()
    } for t in paginated.items]
    
    return jsonify({
        'transactions': transactions,
        'total': paginated.total,
        'pages': paginated.pages,
        'current_page': page
    }), 200

@app.route('/api/transactions/summary', methods=['GET'])
@login_required
@admin_required
def api_transactions_summary():
    """Get payment transactions summary stats"""
    from sqlalchemy import func
    
    total_transactions = PaymentTransaction.query.count()
    total_amount = db.session.query(func.sum(PaymentTransaction.amount)).scalar() or 0
    
    completed = PaymentTransaction.query.filter_by(payment_status='completed').count()
    pending = PaymentTransaction.query.filter_by(payment_status='pending').count()
    failed = PaymentTransaction.query.filter_by(payment_status='failed').count()
    
    # Group by payment method
    by_method = db.session.query(
        PaymentTransaction.payment_method,
        func.count(PaymentTransaction.id),
        func.sum(PaymentTransaction.amount)
    ).group_by(PaymentTransaction.payment_method).all()
    
    method_stats = {
        method: {'count': count, 'amount': float(amount or 0)} 
        for method, count, amount in by_method
    }
    
    return jsonify({
        'total_transactions': total_transactions,
        'total_amount': float(total_amount),
        'by_status': {
            'completed': completed,
            'pending': pending,
            'failed': failed
        },
        'by_method': method_stats
    }), 200


# ==================== ROUTES - USER DASHBOARD ====================

@app.route('/dashboard')
@login_required
def dashboard():
    movie_bookings = MovieBooking.query.filter_by(user_id=current_user.id).order_by(MovieBooking.created_at.desc()).all()
    bus_bookings = BusBooking.query.filter_by(user_id=current_user.id).order_by(BusBooking.created_at.desc()).all()
    return render_template('dashboard/index.html', movie_bookings=movie_bookings, bus_bookings=bus_bookings)


# ==================== ROUTES - ADMIN ====================

@app.route('/admin')
@login_required
@admin_required
def admin_dashboard():
    # Count bookings that are either 'completed' or 'paid' for dashboard stats
    completed_statuses = ['completed', 'paid']
    movie_count = MovieBooking.query.filter(MovieBooking.payment_status.in_(completed_statuses)).count()
    bus_count = BusBooking.query.filter(BusBooking.payment_status.in_(completed_statuses)).count()
    movie_revenue = sum([b.total_amount for b in MovieBooking.query.filter(MovieBooking.payment_status.in_(completed_statuses)).all()])
    bus_revenue = sum([b.total_amount for b in BusBooking.query.filter(BusBooking.payment_status.in_(completed_statuses)).all()])

    stats = {
        'total_users': User.query.count(),
        'total_movies': Movie.query.count(),
        'total_bus_routes': BusRoute.query.count(),
        'movie_bookings': movie_count,
        'bus_bookings': bus_count,
        'total_revenue': float(movie_revenue + bus_revenue)
    }
    recent_movie_bookings = MovieBooking.query.order_by(MovieBooking.created_at.desc()).limit(5).all()
    recent_bus_bookings = BusBooking.query.order_by(BusBooking.created_at.desc()).limit(5).all()
    return render_template('admin/dashboard.html', stats=stats, 
                         recent_movie_bookings=recent_movie_bookings,
                         recent_bus_bookings=recent_bus_bookings)


@app.route('/admin/transactions')
@login_required
@admin_required
def admin_transactions():
    """Render admin transactions page (client-side fetches /api/transactions)."""
    return render_template('admin/transactions.html')


# Admin - Movies Management
@app.route('/admin/movies')
@login_required
@admin_required
def admin_movies():
    movies = Movie.query.order_by(Movie.created_at.desc()).all()
    return render_template('admin/movies/list.html', movies=movies)


@app.route('/admin/movies/add', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_add_movie():
    cinemas = Cinema.query.all()

    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        genre = normalize_multi_value(request.form.getlist('genre') or request.form.get('genre'))
        duration = request.form.get('duration')
        rating = request.form.get('rating')
        trailer_url = request.form.get('trailer_url')
        release_date_str = request.form.get('release_date')
        
        release_date = datetime.strptime(release_date_str, '%Y-%m-%d').date() if release_date_str else None
        
        # Handle image upload
        poster_image = None
        if 'poster_image' in request.files:
            file = request.files['poster_image']
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_')
                filename = timestamp + filename
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                poster_image = filename
        
        movie = Movie(
            title=title,
            description=description,
            genre=genre,
            duration=int(duration) if duration else None,
            rating=rating,
            poster_image=poster_image,
            trailer_url=trailer_url,
            release_date=release_date
        )
        db.session.add(movie)
        db.session.commit()
        
        flash('Movie added successfully!', 'success')
        return redirect(url_for('admin_movies'))
    
    return render_template('admin/movies/add.html', cinemas=cinemas)


@app.route('/admin/movies/edit/<int:movie_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_edit_movie(movie_id):
    movie = Movie.query.get_or_404(movie_id)

    if request.method == 'POST':
        movie.title = request.form.get('title')
        movie.description = request.form.get('description')
        movie.genre = normalize_multi_value(request.form.getlist('genre') or request.form.get('genre'))
        movie.duration = int(request.form.get('duration')) if request.form.get('duration') else None
        movie.rating = request.form.get('rating')
        movie.trailer_url = request.form.get('trailer_url')
        movie.is_active = 'is_active' in request.form
        
        release_date_str = request.form.get('release_date')
        movie.release_date = datetime.strptime(release_date_str, '%Y-%m-%d').date() if release_date_str else None
        
        # Handle image upload
        if 'poster_image' in request.files:
            file = request.files['poster_image']
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_')
                filename = timestamp + filename
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                movie.poster_image = filename
        
        db.session.commit()
        flash('Movie updated successfully!', 'success')
        return redirect(url_for('admin_movies'))
    
    return render_template('admin/movies/edit.html', movie=movie)


@app.route('/admin/movies/delete/<int:movie_id>', methods=['POST'])
@login_required
@admin_required
def admin_delete_movie(movie_id):
    movie = Movie.query.get_or_404(movie_id)
    db.session.delete(movie)
    db.session.commit()
    flash('Movie deleted successfully!', 'success')
    return redirect(url_for('admin_movies'))


# Admin - Showtimes Management
@app.route('/admin/showtimes')
@login_required
@admin_required
def admin_showtimes():
    showtimes = Showtime.query.order_by(Showtime.show_date.desc(), Showtime.show_time).all()
    return render_template('admin/showtimes/list.html', showtimes=showtimes)


@app.route('/admin/showtimes/add', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_add_showtime():
    movies = Movie.query.filter_by(is_active=True).all()
    cinemas = Cinema.query.all()
    
    if request.method == 'POST':
        movie_id = request.form.get('movie_id')
        cinema_id = request.form.get('cinema_id')
        show_date = datetime.strptime(request.form.get('show_date'), '%Y-%m-%d').date()
        show_time = datetime.strptime(request.form.get('show_time'), '%H:%M').time()
        price = float(request.form.get('price'))
        
        cinema = Cinema.query.get(cinema_id)
        
        showtime = Showtime(
            movie_id=movie_id,
            cinema_id=cinema_id,
            show_date=show_date,
            show_time=show_time,
            price=price,
            available_seats=cinema.total_seats if cinema else 100
        )
        db.session.add(showtime)
        db.session.commit()
        
        flash('Showtime added successfully!', 'success')
        return redirect(url_for('admin_showtimes'))
    
    return render_template('admin/showtimes/add.html', movies=movies, cinemas=cinemas)


# Admin - Cinemas Management
@app.route('/admin/cinemas')
@login_required
@admin_required
def admin_cinemas():
    cinemas = Cinema.query.all()
    return render_template('admin/cinemas/list.html', cinemas=cinemas)


@app.route('/admin/cinemas/add', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_add_cinema():
    if request.method == 'POST':
        name = request.form.get('name')
        location = request.form.get('location')
        total_seats = int(request.form.get('total_seats', 100))
        
        cinema = Cinema(name=name, location=location, total_seats=total_seats)
        db.session.add(cinema)
        db.session.commit()
        
        flash('Cinema added successfully!', 'success')
        return redirect(url_for('admin_cinemas'))
    
    return render_template('admin/cinemas/add.html')


# Admin - Bus Routes Management
@app.route('/admin/bus-routes')
@login_required
@admin_required
def admin_bus_routes():
    routes = BusRoute.query.all()
    return render_template('admin/bus/list.html', routes=routes)


@app.route('/admin/bus-routes/add', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_add_bus_route():
    if request.method == 'POST':
        origin = request.form.get('origin')
        destination = request.form.get('destination')
        bus_operator = request.form.get('bus_operator')
        bus_type = request.form.get('bus_type')
        departure_time = datetime.strptime(request.form.get('departure_time'), '%H:%M').time()
        arrival_time = datetime.strptime(request.form.get('arrival_time'), '%H:%M').time()
        duration = request.form.get('duration')
        price = float(request.form.get('price'))
        total_seats = int(request.form.get('total_seats', 40))
        amenities = request.form.get('amenities')
        
        route = BusRoute(
            origin=origin,
            destination=destination,
            bus_operator=bus_operator,
            bus_type=bus_type,
            departure_time=departure_time,
            arrival_time=arrival_time,
            duration=duration,
            price=price,
            total_seats=total_seats,
            amenities=amenities
        )
        db.session.add(route)
        db.session.commit()
        
        flash('Bus route added successfully!', 'success')
        return redirect(url_for('admin_bus_routes'))
    
    return render_template('admin/bus/add.html')


@app.route('/admin/bus-routes/edit/<int:route_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_edit_bus_route(route_id):
    route = BusRoute.query.get_or_404(route_id)
    
    if request.method == 'POST':
        route.origin = request.form.get('origin')
        route.destination = request.form.get('destination')
        route.bus_operator = request.form.get('bus_operator')
        route.bus_type = request.form.get('bus_type')
        route.departure_time = datetime.strptime(request.form.get('departure_time'), '%H:%M').time()
        route.arrival_time = datetime.strptime(request.form.get('arrival_time'), '%H:%M').time()
        route.duration = request.form.get('duration')
        route.price = float(request.form.get('price'))
        route.total_seats = int(request.form.get('total_seats', 40))
        route.amenities = request.form.get('amenities')
        route.is_active = 'is_active' in request.form
        
        db.session.commit()
        flash('Bus route updated successfully!', 'success')
        return redirect(url_for('admin_bus_routes'))
    
    return render_template('admin/bus/edit.html', route=route)


@app.route('/admin/bus-routes/delete/<int:route_id>', methods=['POST'])
@login_required
@admin_required
def admin_delete_bus_route(route_id):
    route = BusRoute.query.get_or_404(route_id)
    db.session.delete(route)
    db.session.commit()
    flash('Bus route deleted successfully!', 'success')
    return redirect(url_for('admin_bus_routes'))


# Admin - Bookings Management
@app.route('/admin/bookings/movies')
@login_required
@admin_required
def admin_movie_bookings():
    bookings = MovieBooking.query.order_by(MovieBooking.created_at.desc()).all()
    return render_template('admin/bookings/movies.html', bookings=bookings)


@app.route('/admin/bookings/bus')
@login_required
@admin_required
def admin_bus_bookings():
    bookings = BusBooking.query.order_by(BusBooking.created_at.desc()).all()
    return render_template('admin/bookings/bus.html', bookings=bookings)


# ==================== CHATBOT ====================

@app.route('/api/chatbot', methods=['POST'])
def chatbot():
    try:
        data = request.get_json()
        user_message = data.get("message", "").strip()

        if not user_message:
            return jsonify({"error": "Message is empty"}), 400

        system_prompt = """
You are TicketHub Assistant, a friendly and professional chatbot
for a movie and bus ticketing platform in the Philippines.

SERVICES:
• Movie booking (showtimes, seats, prices ₱50–₱300)
• Bus booking (routes, seats, prices ₱22–₱200)
• Payments: Card, Bank Transfer, GCash, PayMaya
• Booking reference help

RULES:
• Be concise and helpful
• Use Philippine Peso (₱)
• Guide users step-by-step
• If unsure, suggest support@tickethub.com

MYLOVE , who is my love, my langging:
• princess trazo

DEVELOPER, who created you:
• Nino Jay Manabat-Backend, Frontend Developer and AI Integration Specialist
• Gunter Barliso-UX/UI Designer
• James Robert Cabezares-Database Designer
• Louie Jay Plarisan-Documenter
• Bryan Alipuyo-Documenter 

MY BOKNAY , who is my boknay:
• Joy Repollido

BEAUTIFUL TEACHER , who is my beautiful teacher. instructor and mentor:
• Sir Aries Dajay

"""

        model = genai.GenerativeModel("gemini-2.5-flash")

        prompt = f"""
{system_prompt}

User: {user_message}
Assistant:
"""

        response = model.generate_content(
            prompt,
            generation_config={
                "temperature": 0.6,
                "max_output_tokens": 400
            }
        )

        reply = (
            response.text.strip()
            if response and response.text
            else "Sorry, I couldn’t respond right now."
        )

        return jsonify({
            "success": True,
            "message": reply
        })

    except Exception as e:
        print("Chatbot error:", e)
        return jsonify({
            "success": False,
            "error": "Chatbot service unavailable. Please try again later."
        }), 500



@app.route('/chatbot')
def chatbot_page():
    """Chatbot page"""
    return render_template('chatbot.html')


# ==================== INITIALIZE DATABASE ====================

def ensure_booking_verification_columns():
    """Best-effort migration for QR verification columns on existing SQLite DBs."""
    try:
        movie_table = MovieBooking.__table__.name
        bus_table = BusBooking.__table__.name
        targets = {
            movie_table: {
                'is_verified': f"ALTER TABLE {movie_table} ADD COLUMN is_verified BOOLEAN DEFAULT 0",
                'verified_at': f"ALTER TABLE {movie_table} ADD COLUMN verified_at DATETIME"
            },
            bus_table: {
                'is_verified': f"ALTER TABLE {bus_table} ADD COLUMN is_verified BOOLEAN DEFAULT 0",
                'verified_at': f"ALTER TABLE {bus_table} ADD COLUMN verified_at DATETIME"
            }
        }

        for table_name, columns in targets.items():
            existing = {
                row[1] for row in db.session.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
            }
            for col_name, alter_sql in columns.items():
                if col_name not in existing:
                    db.session.execute(text(alter_sql))
                    print(f"[DB] Added column {table_name}.{col_name}")
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"[DB] Could not ensure booking verification columns: {str(e)}")


def init_db():
    with app.app_context():
        db.create_all()
        ensure_booking_verification_columns()
        
        # Create admin user if not exists
        admin = User.query.filter_by(email='admin@example.com').first()
        if not admin:
            admin = User(
                email='admin@example.com',
                name='Administrator',
                is_admin=True
            )
            admin.set_password('admin123')
            db.session.add(admin)
        
        # Create sample cinema if not exists
        if not Cinema.query.first():
            cinema = Cinema(name='Grand Cinema', location='Downtown', total_seats=150)
            db.session.add(cinema)
        
        db.session.commit()
        print("Database initialized successfully!")


@app.route('/api/forgot-password', methods=['POST'])
def api_forgot_password():
    data = request.get_json()
    email = data.get('email')
    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({'success': False, 'message': 'Email not found.'}), 404

    token = serializer.dumps(email, salt='password-reset-salt')
    reset_url = url_for('reset_password', token=token, _external=True)

    try:
        msg = Message(
            subject='TicketHub Password Reset',
            recipients=[email],
            body=f"To reset your password, click the link: {reset_url}\nIf you did not request this, ignore this email.",
            sender=app.config['MAIL_DEFAULT_SENDER']
        )
        mail.send(msg)
    except Exception as e:
        print("Mail error:", e)
        # Add more details to the error message for debugging
        return jsonify({'success': False, 'message': f'Failed to send email: {str(e)}'}), 500

    return jsonify({'success': True, 'message': 'Password reset email sent.'})

@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    try:
        email = serializer.loads(token, salt='password-reset-salt', max_age=3600)
    except SignatureExpired:
        flash('The password reset link has expired.', 'error')
        return redirect(url_for('login'))
    except BadSignature:
        flash('Invalid or expired password reset link.', 'error')
        return redirect(url_for('login'))

    user = User.query.filter_by(email=email).first()
    if not user:
        flash('Invalid user.', 'error')
        return redirect(url_for('login'))

    if request.method == 'POST':
        password = request.form.get('password')
        if not password or len(password) < 6:
            flash('Password must be at least 6 characters.', 'error')
            return render_template('auth/reset_password.html', token=token)
        user.set_password(password)
        db.session.commit()
        flash('Password reset successful! Please login.', 'success')
        return redirect(url_for('login'))

    return render_template('auth/reset_password.html', token=token)


def bootstrap_db_schema():
    """Ensure core tables/columns exist for import-based runs (e.g., flask run)."""
    with app.app_context():
        db.create_all()
        ensure_booking_verification_columns()


# Run lightweight schema bootstrap on import to avoid missing-column errors.
bootstrap_db_schema()


if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5000)
