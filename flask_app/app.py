"""
Movie + Bus Ticketing Platform
Flask Application with SQLAlchemy, PayMongo Payments (Card, GCash, PayMaya, PayPal), and Admin Panel
"""

import os, base64
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

# Load environment variables from .env file
load_dotenv()

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
    secret_key = os.environ.get("PAYMONGO_SECRET_KEY")
    if not secret_key:
        print("[PayMongo] ⚠️  WARNING: PAYMONGO_SECRET_KEY not set in environment!")
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


# ==================== PayMongo Helper Functions ====================

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

def pm_create_source(amount_cents, type_name, currency='PHP', redirect_urls=None, metadata=None):
    """Create a PayMongo Source (for e-wallet, bank_transfer, etc.)"""
    try:
        payload = {"data": {"attributes": {"amount": amount_cents, "currency": currency, "type": type_name}}}
        if redirect_urls:
            payload["data"]["attributes"]["redirect"] = redirect_urls
        if metadata:
            payload["data"]["attributes"]["metadata"] = metadata
        resp = requests.post('https://api.paymongo.com/v1/sources', json=payload, headers=paymongo_headers(), timeout=15)
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

def send_booking_confirmation_email(user, booking_type, booking):
    """Send booking confirmation email to user"""
    try:
        if booking_type == 'movie':
            subject = f"🎬 Movie Booking Confirmed - {booking.booking_reference}"
            showtime = booking.showtime
            movie = showtime.movie
            cinema = showtime.cinema
            
            body = f"""
Hello {user.name},

Your movie booking has been confirmed successfully!

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📽️ MOVIE BOOKING CONFIRMATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Booking Reference: {booking.booking_reference}
Movie: {movie.title}
Cinema: {cinema.name}
Date: {showtime.show_date.strftime('%B %d, %Y')}
Time: {showtime.show_time.strftime('%I:%M %p')}
Number of Tickets: {booking.num_tickets}
Seat Numbers: {booking.seat_numbers if booking.seat_numbers else 'To be assigned'}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
💳 PAYMENT DETAILS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Amount Paid: ₱{booking.total_amount:.2f}
Payment Method: {booking.payment_method.upper()}
Status: PAID ✓

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Please arrive 15 minutes before the show time. Have your booking reference ready at the ticket counter.

For cancellations or inquiries, please contact us within 24 hours.

Best regards,
TicketHub Team
"""
        else:  # bus booking
            subject = f"🚌 Bus Booking Confirmed - {booking.booking_reference}"
            schedule = booking.schedule
            route = schedule.route
            
            body = f"""
Hello {user.name},

Your bus booking has been confirmed successfully!

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🚌 BUS BOOKING CONFIRMATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Booking Reference: {booking.booking_reference}
Route: {route.origin} → {route.destination}
Bus Operator: {route.bus_operator}
Bus Type: {route.bus_type}
Travel Date: {schedule.travel_date.strftime('%B %d, %Y')}
Departure Time: {route.departure_time.strftime('%I:%M %p')}
Arrival Time: {route.arrival_time.strftime('%I:%M %p')}
Number of Passengers: {booking.num_tickets}
Seat Numbers: {booking.seat_numbers if booking.seat_numbers else 'To be assigned'}

Amenities: {route.amenities if route.amenities else 'Standard amenities'}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
💳 PAYMENT DETAILS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Amount Paid: ₱{booking.total_amount:.2f}
Payment Method: {booking.payment_method.upper()}
Status: PAID ✓

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Please arrive at the boarding point 30 minutes before the departure time. Keep your booking reference and ID handy.

For cancellations or inquiries, please contact us within 24 hours.

Best regards,
TicketHub Team
"""

        # Send email
        msg = Message(
            subject=subject,
            recipients=[user.email],
            body=body
        )
        mail.send(msg)
        print(f"[Email] ✓ Booking confirmation sent to {user.email} (Ref: {booking.booking_reference})")
        return True
    except Exception as e:
        print(f"[Email] ✗ Failed to send booking confirmation email: {str(e)}")
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


# ==================== ROUTES - MAIN ====================

@app.route('/')
def index():
    movies = Movie.query.filter_by(is_active=True).order_by(Movie.release_date.desc()).limit(6).all()
    routes = BusRoute.query.filter_by(is_active=True).limit(6).all()

    # Build availability maps for movies (next upcoming showtime) and bus routes (next schedule)
    from datetime import date
    availability_map = {}
    for m in movies:
        try:
            next_show = Showtime.query.filter(
                Showtime.movie_id == m.id,
                Showtime.show_date >= datetime.now().date()
            ).order_by(Showtime.show_date, Showtime.show_time).first()
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
    movies = Movie.query.filter_by(is_active=True).order_by(Movie.release_date.desc()).all()
    return render_template('movies/list.html', movies=movies)


@app.route('/movies/<int:movie_id>')
def movie_detail(movie_id):
    movie = Movie.query.get_or_404(movie_id)
    showtimes = Showtime.query.filter(
        Showtime.movie_id == movie_id,
        Showtime.show_date >= datetime.now().date()
    ).order_by(Showtime.show_date, Showtime.show_time).all()
    return render_template('movies/detail.html', movie=movie, showtimes=showtimes)


@app.route('/movies/book/<int:showtime_id>', methods=['GET', 'POST'])
@login_required
def book_movie(showtime_id):
    showtime = Showtime.query.get_or_404(showtime_id)
    
    if request.method == 'POST':
        num_tickets = int(request.form.get('num_tickets', 1))
        seat_numbers = request.form.get('seat_numbers', '')
        
        # Basic availability check
        if num_tickets > (showtime.available_seats or 0):
            flash('Not enough seats available.', 'error')
            return redirect(url_for('book_movie', showtime_id=showtime_id))

        # Validate seat selection: parse and ensure count matches
        selected = [s.strip() for s in seat_numbers.split(',') if s.strip()]
        if len(selected) != num_tickets:
            flash(f'Please select exactly {num_tickets} seat(s).', 'error')
            return redirect(url_for('book_movie', showtime_id=showtime_id))

        # Check for duplicate seats in submission
        if len(set(selected)) != len(selected):
            flash('Duplicate seat selection detected. Please choose different seats.', 'error')
            return redirect(url_for('book_movie', showtime_id=showtime_id))

        # Check against already reserved seats (pending/paid/completed)
        reserved_statuses = ['pending', 'paid', 'completed']
        existing = MovieBooking.query.filter(MovieBooking.showtime_id == showtime_id, MovieBooking.payment_status.in_(reserved_statuses)).all()
        reserved = set()
        for b in existing:
            if b.seat_numbers:
                for s in b.seat_numbers.split(','):
                    s2 = s.strip()
                    if s2:
                        reserved.add(s2)

        conflicts = [s for s in selected if s in reserved]
        if conflicts:
            flash(f'The following seat(s) are no longer available: {", ".join(conflicts)}. Please choose different seats.', 'error')
            return redirect(url_for('book_movie', showtime_id=showtime_id))
        
        total_amount = num_tickets * showtime.price
        booking_ref = generate_booking_reference()
        
        booking = MovieBooking(
            user_id=current_user.id,
            showtime_id=showtime_id,
            num_tickets=num_tickets,
            seat_numbers=seat_numbers,
            total_amount=total_amount,
            booking_reference=booking_ref
        )
        db.session.add(booking)
        db.session.commit()
        
        return redirect(url_for('payment', booking_type='movie', booking_id=booking.id))
    
    return render_template('movies/book.html', showtime=showtime)


# ==================== ROUTES - BUS ====================

@app.route('/bus')
def bus_routes():
    routes = BusRoute.query.filter_by(is_active=True).all()
    return render_template('bus/list.html', routes=routes)


@app.route('/bus/search', methods=['GET', 'POST'])
def search_bus():
    if request.method == 'POST':
        origin = request.form.get('origin')
        destination = request.form.get('destination')
        travel_date = request.form.get('travel_date')
        
        routes = BusRoute.query.filter(
            BusRoute.origin.ilike(f'%{origin}%'),
            BusRoute.destination.ilike(f'%{destination}%'),
            BusRoute.is_active == True
        ).all()
        
        return render_template('bus/search_results.html', 
                             routes=routes, 
                             origin=origin, 
                             destination=destination,
                             travel_date=travel_date)
    
    return render_template('bus/search.html')


@app.route('/bus/book/<int:route_id>', methods=['GET', 'POST'])
@login_required
def book_bus(route_id):
    route = BusRoute.query.get_or_404(route_id)
    travel_date = request.args.get('date', datetime.now().date().isoformat())
    
    # Get or create schedule for the date
    schedule = BusSchedule.query.filter_by(
        route_id=route_id,
        travel_date=datetime.strptime(travel_date, '%Y-%m-%d').date()
    ).first()
    
    if not schedule:
        schedule = BusSchedule(
            route_id=route_id,
            travel_date=datetime.strptime(travel_date, '%Y-%m-%d').date(),
            available_seats=route.total_seats
        )
        db.session.add(schedule)
        db.session.commit()
    
    if request.method == 'POST':
        num_tickets = int(request.form.get('num_tickets', 1))
        seat_numbers = request.form.get('seat_numbers', '')
        passenger_names = request.form.get('passenger_names', '')
        
        if num_tickets > schedule.available_seats:
            flash('Not enough seats available.', 'error')
            return redirect(url_for('book_bus', route_id=route_id, date=travel_date))
        
        total_amount = num_tickets * route.price
        booking_ref = generate_booking_reference()
        
        booking = BusBooking(
            user_id=current_user.id,
            schedule_id=schedule.id,
            num_tickets=num_tickets,
            seat_numbers=seat_numbers,
            passenger_names=passenger_names,
            total_amount=total_amount,
            booking_reference=booking_ref
        )
        db.session.add(booking)
        db.session.commit()
        
        return redirect(url_for('payment', booking_type='bus', booking_id=booking.id))
    
    return render_template('bus/book.html', route=route, schedule=schedule, travel_date=travel_date)


# ==================== ROUTES - PAYMENT ====================

@app.route('/payment/<booking_type>/<int:booking_id>')
@login_required
def payment(booking_type, booking_id):
    if booking_type == 'movie':
        booking = MovieBooking.query.get_or_404(booking_id)
    else:
        booking = BusBooking.query.get_or_404(booking_id)
    
    if booking.user_id != current_user.id:
        flash('Unauthorized access.', 'error')
        return redirect(url_for('index'))
    
    return render_template('payment/checkout.html', 
                         booking=booking, 
                         booking_type=booking_type)


@app.route('/create-payment-intent', methods=['POST'])
@login_required
def create_payment_intent():
    data = request.get_json()
    booking_type = data.get('booking_type')
    booking_id = data.get('booking_id')
    payment_method = data.get('payment_method', 'card')  # Accept payment method; default to card

    if booking_type == 'movie':
        booking = MovieBooking.query.get_or_404(booking_id)
    else:
        booking = BusBooking.query.get_or_404(booking_id)

    # Create a PayMongo "source" (redirect) so we can send the user to PayMongo's hosted flow.
    try:
        amount = int(booking.total_amount * 100)  # PayMongo expects amount in centavos

        success_url = url_for('payment_success_page', booking_type=booking_type, booking_id=booking.id, _external=True)
        failed_url = success_url  # fallback to same page; webhook will update status

        payload = {
            "data": {
                "attributes": {
                    "amount": amount,
                    "currency": "PHP",
                    "type": payment_method,
                    "redirect": {
                        "success": success_url,
                        "failed": failed_url
                    },
                    "metadata": {
                        "booking_type": booking_type,
                        "booking_id": str(booking_id),
                        "booking_reference": booking.booking_reference
                    }
                }
            }
        }

        resp = requests.post('https://api.paymongo.com/v1/sources', json=payload, headers=paymongo_headers(), timeout=15)
        resp.raise_for_status()
        data = resp.json()

        # Try to extract a redirect/checkout URL from PayMongo response
        checkout_url = None
        source_id = None
        try:
            source_id = data['data']['id']
            attrs = data['data'].get('attributes', {})
            redirect_info = attrs.get('redirect', {})
            checkout_url = redirect_info.get('checkout_url') or redirect_info.get('url') or redirect_info.get('redirect_url')
        except Exception:
            pass

        # Save tracking info on booking - DO NOT override if already set by /payment-ewallet-pending
        if not booking.payment_method:
            booking.payment_method = payment_method
        booking.payment_reference = source_id or booking.payment_reference
        booking.payment_status = 'pending'
        db.session.commit()

        return jsonify({'checkout_url': checkout_url, 'source_id': source_id})
    except requests.RequestException as e:
        return jsonify({'error': 'Failed to create PayMongo source', 'details': str(e)}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/confirm-gcash-payment', methods=['POST'])
@login_required
def confirm_gcash_payment():
    """Confirm a GCash payment by checking PayMongo for a completed payment linked to the source or booking."""
    data = request.get_json() or {}
    booking_type = data.get('booking_type')
    booking_id = data.get('booking_id')
    source_id = data.get('source_id')

    if booking_type == 'movie':
        booking = MovieBooking.query.get_or_404(booking_id)
    else:
        booking = BusBooking.query.get_or_404(booking_id)

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
            booking.payment_status = 'paid'
            booking.payment_method = 'gcash'
            # store paymongo payment id
            booking.payment_reference = payment_id or booking.payment_reference

            # decrement seats safely
            if booking_type == 'movie':
                try:
                    showtime = booking.showtime
                    if showtime and showtime.available_seats is not None:
                        showtime.available_seats = max(0, showtime.available_seats - booking.num_tickets)
                except Exception:
                    pass
            else:
                try:
                    schedule = booking.schedule
                    if schedule and schedule.available_seats is not None:
                        schedule.available_seats = max(0, schedule.available_seats - booking.num_tickets)
                except Exception:
                    pass

            db.session.commit()

            # Log transaction (record who completed the payment)
            log_payment_transaction(
                user_id=booking.user_id,
                booking_type=booking_type,
                booking_id=booking.id,
                booking_ref=booking.booking_reference,
                amount=booking.total_amount,
                payment_method='gcash',
                status='completed',
                source_id=source_id,
                completed_by=current_user.id
            )

            # Send booking confirmation email
            try:
                send_booking_confirmation_email(booking.user, booking_type, booking)
            except Exception as e:
                print(f"[GCash Confirm] Failed to send confirmation email: {str(e)}")

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
    payer_name = data.get('payer_name')

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
        statuses = ['pending', 'paid', 'completed']
        bookings = MovieBooking.query.filter(MovieBooking.showtime_id == showtime_id, MovieBooking.payment_status.in_(statuses)).all()
        for booking in bookings:
            if booking.seat_numbers:
                seats = [s.strip() for s in booking.seat_numbers.split(',') if s.strip()]
                booked_seats.extend(seats)
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
    reserved_statuses = ['pending', 'paid', 'completed']
    booked = []
    try:
        bookings = MovieBooking.query.filter(MovieBooking.showtime_id == showtime_id, MovieBooking.payment_status.in_(reserved_statuses)).all()
        for b in bookings:
            if b.seat_numbers:
                for s in b.seat_numbers.split(','):
                    s2 = s.strip()
                    if s2:
                        booked.append(s2)
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
    try:
        bookings = BusBooking.query.filter(BusBooking.schedule_id == schedule_id, BusBooking.payment_status.in_(reserved_statuses)).all()
        for b in bookings:
            if b.seat_numbers:
                for s in b.seat_numbers.split(','):
                    s2 = s.strip()
                    if s2:
                        booked.append(s2)
    except Exception as e:
        print(f"[API] Error collecting booked seats for schedule {schedule_id}: {e}")

    all_seats = [str(i) for i in range(1, total + 1)]
    booked_set = set(booked)
    available = [s for s in all_seats if s not in booked_set]

    return jsonify({
        'schedule_id': schedule_id,
        'total_seats': total,
        'booked_seats': sorted(list(booked_set), key=lambda x: int(x) if x.isdigit() else x),
        'available_seats': available,
        'available_count': len(available)
    }), 200


@app.route('/get-booked-bus-seats', methods=['POST'])
def get_booked_bus_seats():
    data = request.get_json()
    schedule_id = data.get('schedule_id')
    
    # Get all completed bookings for this bus schedule
    bookings = BusBooking.query.filter_by(schedule_id=schedule_id, payment_status='completed').all()
    
    booked_seats = []
    for booking in bookings:
        if booking.seat_numbers:
            seats = booking.seat_numbers.split(',')
            booked_seats.extend(seats)
    
    return jsonify({'booked_seats': booked_seats})

# ----------------------
# Payment Page
# ----------------------
@app.route('/payment/<booking_type>/<int:booking_id>')
@login_required
def payment_page(booking_type, booking_id):
    if booking_type == 'movie':
        booking = MovieBooking.query.get_or_404(booking_id)
    else:
        booking = BusBooking.query.get_or_404(booking_id)

    return render_template(
        'payment.html',
        booking=booking,
        booking_type=booking_type
    )

@app.route('/payment-ewallet-pending', methods=['POST'])
@login_required
def payment_ewallet_pending():
    data = request.get_json()
    booking_type = data.get("booking_type")
    booking_id = data.get("booking_id")
    payment_method = data.get("payment_method")  # gcash, paymaya, paypal, card

    # Validate required fields
    if not all([booking_type, booking_id, payment_method]):
        return jsonify({"success": False, "error": "Missing required fields: booking_type, booking_id, payment_method"}), 400

    # Get booking
    try:
        if booking_type == 'movie':
            booking = MovieBooking.query.get_or_404(booking_id)
        else:
            booking = BusBooking.query.get_or_404(booking_id)
    except Exception as e:
        return jsonify({"success": False, "error": f"Booking not found: {str(e)}"}), 404

    # Normalize payment method type
    pm_type = payment_method.lower().strip()
    
    # PayMongo valid source types
    valid_types = ["gcash", "paymaya", "paypal", "card", "grab_pay", "ddoc"]
    if pm_type not in valid_types:
        return jsonify({"success": False, "error": f"Invalid payment method: {pm_type}. Valid types: {', '.join(valid_types)}"}), 400

    try:
        amount = int(booking.total_amount * 100)
        if amount <= 0:
            return jsonify({"success": False, "error": "Invalid booking amount"}), 400

        success_url = url_for('payment_success_page', booking_type=booking_type, booking_id=booking.id, _external=True)
        failed_url = success_url

        payload = {
            "data": {
                "attributes": {
                    "amount": amount,
                    "currency": "PHP",
                    "type": pm_type,
                    "redirect": {
                        "success": success_url,
                        "failed": failed_url
                    },
                    "metadata": {
                        "booking_type": booking_type,
                        "booking_id": str(booking_id),
                        "booking_reference": booking.booking_reference
                    }
                }
            }
        }

        print(f"\n[PayMongo] ========== REQUEST ==========")
        print(f"[PayMongo] Endpoint: POST https://api.paymongo.com/v1/sources")
        print(f"[PayMongo] Payment Type: {pm_type}")
        print(f"[PayMongo] Amount: {amount} centavos (₱{booking.total_amount})")
        print(f"[PayMongo] Booking: {booking_type} #{booking_id}")
        
        headers = paymongo_headers()
        print(f"[PayMongo] Auth Header: {headers.get('Authorization', 'MISSING')[:20]}...")
        print(f"[PayMongo] Payload: {payload}\n")
        
        resp = requests.post(
            'https://api.paymongo.com/v1/sources', 
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
            return jsonify({
                "success": False,
                "error": f"PayMongo returned invalid response (status {resp.status_code})",
                "details": resp.text[:200] if resp.text else "Empty response"
            }), 500
        
        if resp.status_code not in (200, 201):
            error_msg = resp_data.get('error', {}).get('message', 'Unknown error')
            error_code = resp_data.get('error', {}).get('code', 'unknown')
            print(f"[PayMongo] ❌ ERROR - Code: {error_code}, Message: {error_msg}\n")
            return jsonify({
                "success": False, 
                "error": f"PayMongo request failed: {error_msg}",
                "error_code": error_code,
                "details": resp_data.get('error', {})
            }), 400
        
        source_id = resp_data.get('data', {}).get('id')
        attrs = resp_data.get('data', {}).get('attributes', {})
        redirect_info = attrs.get('redirect', {}) if isinstance(attrs, dict) else {}
        checkout_url = redirect_info.get('checkout_url') or redirect_info.get('url') or redirect_info.get('redirect_url')

        print(f"[PayMongo] ✓ SUCCESS")
        print(f"[PayMongo] Source ID: {source_id}")
        print(f"[PayMongo] Checkout URL: {checkout_url}\n")

        # Mark booking as pending and store reference
        booking.payment_status = 'pending'
        booking.payment_method = pm_type
        booking.payment_reference = source_id
        
        # Log the payment transaction
        log_payment_transaction(
            user_id=current_user.id,
            booking_type=booking_type,
            booking_id=booking_id,
            booking_ref=booking.booking_reference,
            amount=booking.total_amount,
            payment_method=pm_type,
            status='pending',
            source_id=source_id
        )
        db.session.commit()

        return jsonify({
            "success": True,
            "checkout_url": checkout_url,
            "booking_id": booking.id,
            "booking_type": booking_type,
            "source_id": source_id
        })
    except requests.exceptions.Timeout:
        print(f"[PayMongo] ❌ TIMEOUT - Request took longer than 15 seconds\n")
        return jsonify({"success": False, "error": "PayMongo request timed out. Please try again."}), 500
    except requests.exceptions.ConnectionError as e:
        print(f"[PayMongo] ❌ CONNECTION ERROR: {str(e)}\n")
        return jsonify({"success": False, "error": f"Failed to connect to PayMongo: {str(e)}"}), 500
    except requests.RequestException as e:
        print(f"[PayMongo] ❌ REQUEST ERROR: {str(e)}\n")
        return jsonify({"success": False, "error": f"PayMongo request failed: {str(e)}"}), 500
    except Exception as e:
        print(f"[PayMongo] ❌ UNEXPECTED ERROR: {str(e)}\n")
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": f"Server error: {str(e)}"}), 500


# ----------------------
# E-wallet Payment Success Redirect
# ----------------------
@app.route('/payment-success/<booking_type>/<int:booking_id>')
@login_required
def payment_success_page(booking_type, booking_id):
    if booking_type == 'movie':
        booking = MovieBooking.query.get_or_404(booking_id)
    else:
        booking = BusBooking.query.get_or_404(booking_id)

    # Only mark as paid if not already marked by webhook
    if booking.payment_status != 'paid':
        booking.payment_status = 'paid'
        db.session.commit()
        
        # Log the successful payment transaction
        log_payment_transaction(
            user_id=current_user.id,
            booking_type=booking_type,
            booking_id=booking_id,
            booking_ref=booking.booking_reference,
            amount=booking.total_amount,
            payment_method=booking.payment_method or 'card',
            status='completed',
            source_id=booking.payment_reference,
            completed_by=current_user.id
        )
        
        # Send booking confirmation email
        send_booking_confirmation_email(current_user, booking_type, booking)

    return render_template(
        "payment/success.html",
        booking=booking,
        booking_type=booking_type
    )

# ----------------------
# PayMongo Webhook (Optional if using dynamic intents)
# ----------------------
@app.route('/webhook/paymongo', methods=['POST'])
def paymongo_webhook():
    payload = request.get_json() or {}

    # Try to extract event type and resource id / metadata in a tolerant way
    event_type = None
    source_id = None
    metadata = {}

    try:
        data = payload.get('data', {})
        # event type
        attributes = data.get('attributes') if isinstance(data, dict) else None
        if attributes and isinstance(attributes, dict):
            event_type = attributes.get('type')

            # Try nested data -> attributes -> metadata
            nested = attributes.get('data') or {}
            if isinstance(nested, dict):
                nested_attrs = nested.get('attributes') or {}
                metadata = nested_attrs.get('metadata') or nested.get('metadata') or metadata
                source_id = nested.get('id') or nested_attrs.get('id') or source_id

        # Fallbacks
        if not source_id:
            source_id = data.get('id') or payload.get('id')
        if not metadata:
            # try attributes.metadata location
            if attributes:
                metadata = attributes.get('metadata') or {}
    except Exception:
        pass

    # Attempt to find booking using metadata booking_id or booking_reference or by stored source id
    booking = None
    try:
        if metadata and metadata.get('booking_id'):
            bid = int(metadata.get('booking_id'))
            booking = MovieBooking.query.get(bid) or BusBooking.query.get(bid)

        if not booking and metadata and metadata.get('booking_reference'):
            booking = MovieBooking.query.filter_by(booking_reference=metadata.get('booking_reference')).first() \
                      or BusBooking.query.filter_by(booking_reference=metadata.get('booking_reference')).first()

        if not booking and source_id:
            booking = MovieBooking.query.filter_by(payment_reference=source_id).first() \
                      or BusBooking.query.filter_by(payment_reference=source_id).first() 
    except Exception:
        booking = None

    if not booking:
        return jsonify({"error": "booking not found"}), 404

    # Only transition to paid once and decrement seats once
    if event_type and ("paid" in event_type or "succeeded" in event_type or "source.chargeable" in event_type or "source.succeeded" in event_type or "source.completed" in event_type):
        if booking.payment_status != 'paid':
            booking.payment_status = 'paid'
            # Preserve payment method that was set in /payment-ewallet-pending
            # Only set to 'ewallet' if truly unknown
            if not booking.payment_method or booking.payment_method == 'pending':
                booking.payment_method = 'ewallet'
            # decrement seats safely
            if isinstance(booking, MovieBooking):
                try:
                    showtime = booking.showtime
                    if showtime and showtime.available_seats is not None:
                        showtime.available_seats = max(0, showtime.available_seats - booking.num_tickets)
                except Exception:
                    pass
            else:
                try:
                    schedule = booking.schedule
                    if schedule and schedule.available_seats is not None:
                        schedule.available_seats = max(0, schedule.available_seats - booking.num_tickets)
                except Exception:
                    pass

            db.session.commit()
            
            # Log successful payment transaction
            booking_type = 'movie' if isinstance(booking, MovieBooking) else 'bus'
            log_payment_transaction(
                user_id=booking.user_id,
                booking_type=booking_type,
                booking_id=booking.id,
                booking_ref=booking.booking_reference,
                amount=booking.total_amount,
                payment_method=booking.payment_method or 'card',
                status='completed',
                source_id=source_id
            )
            
            # Send booking confirmation email
            booking_type = 'movie' if isinstance(booking, MovieBooking) else 'bus'
            try:
                send_booking_confirmation_email(booking.user, booking_type, booking)
            except Exception as e:
                print(f"[Webhook] Failed to send confirmation email: {str(e)}")
    elif event_type and ("failed" in event_type or "cancelled" in event_type):
        # If payment failed or was cancelled, remove any pending booking so it's not persisted
        booking_type = 'movie' if isinstance(booking, MovieBooking) else 'bus'
        try:
            # Log failed payment transaction first
            log_payment_transaction(
                user_id=booking.user_id,
                booking_type=booking_type,
                booking_id=booking.id,
                booking_ref=booking.booking_reference,
                amount=booking.total_amount,
                payment_method=booking.payment_method or 'card',
                status='failed',
                source_id=source_id
            )

            # Only delete if booking is not already paid
            if booking.payment_status != 'paid':
                db.session.delete(booking)
                db.session.commit()
        except Exception:
            # Fallback: mark as failed if deletion not possible
            try:
                booking.payment_status = 'failed'
                db.session.commit()
            except Exception:
                pass

    return jsonify({"success": True})

@app.route('/check-ewallet-payment/<booking_type>/<int:booking_id>')
@login_required
def check_ewallet_payment(booking_type, booking_id):
    if booking_type == 'movie':
        booking = MovieBooking.query.get_or_404(booking_id)
    else:
        booking = BusBooking.query.get_or_404(booking_id)

    return jsonify({"paid": booking.payment_status == "paid"})


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
    
    secret_key = os.environ.get("PAYMONGO_SECRET_KEY")
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
        resp_data = resp.json() if resp.status_code in (200, 201) else {}
        result["tests"]["create_card_source"] = {
            "status": resp.status_code,
            "success": resp.status_code in (200, 201),
            "message": "✓ Card source created" if resp.status_code in (200, 201) else f"✗ HTTP {resp.status_code}",
            "error": resp_data.get('error', {}).get('message') if resp.status_code not in (200, 201) else None
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
        resp_data = resp.json() if resp.status_code in (200, 201) else {}
        result["tests"]["create_gcash_source"] = {
            "status": resp.status_code,
            "success": resp.status_code in (200, 201),
            "message": "✓ GCash source created" if resp.status_code in (200, 201) else f"✗ HTTP {resp.status_code}",
            "error": resp_data.get('error', {}).get('message') if resp.status_code not in (200, 201) else None
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
        resp_data = resp.json() if resp.status_code in (200, 201) else {}
        result["tests"]["create_paymaya_source"] = {
            "status": resp.status_code,
            "success": resp.status_code in (200, 201),
            "message": "✓ PayMaya source created" if resp.status_code in (200, 201) else f"✗ HTTP {resp.status_code}",
            "error": resp_data.get('error', {}).get('message') if resp.status_code not in (200, 201) else None
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
        genre = request.form.get('genre')
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
        movie.genre = request.form.get('genre')
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
• princess

DEVELOPER, who created you:
• Nino Jay Manabat-Backend, Frontend Developer and AI Integration Specialist
• Gunter Barliso-UX/UI Designer
• James Robert Cabezares-Database Designer
• Louie Jay Plarisan-Documenter
• Bryan Alipuyo-Documenter 

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

def init_db():
    with app.app_context():
        db.create_all()
        
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


if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5000)