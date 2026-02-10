# Movie + Bus Ticketing System

A full-stack Flask application for booking movie and bus tickets with PayMongo payment integration supporting multiple payment methods (Card, GCash, PayMaya, PayPal).

## Features

### User Features
- User registration and authentication
- Browse movies with details (poster, description, cast, etc.)
- Book movie tickets with seat selection
- Search and book bus tickets
- View booking history
- Multiple payment methods: Card, GCash, PayMaya, PayPal via PayMongo
- Payment transaction history and receipts

### Admin Features
- Dashboard with statistics
- Add/Edit/Delete movies with poster upload
- Manage cinemas and showtimes
- Add/Edit/Delete bus routes
- View all bookings

## Tech Stack

- **Backend:** Python Flask
- **Database:** SQLite with SQLAlchemy ORM
- **Authentication:** Flask-Login
- **Payments:** PayMongo (e-wallet, card, bank transfer)
- **Frontend:** Jinja2 Templates, Tailwind CSS
- **File Upload:** Pillow for image processing

## Installation

### Prerequisites
- Python 3.9 or higher
- pip (Python package manager)

### Step 1: Clone and Setup

```bash
cd flask_app
```

### Step 2: Create Virtual Environment

```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment
# On macOS/Linux:
source venv/bin/activate

# On Windows:
venv\Scripts\activate
```

### Step 3: Install Dependencies

```bash
pip install -r requirements.txt
```

### Step 4: Configure Environment Variables

```bash
# Copy example env file
cp .env.example .env

# Edit .env file with your settings
# Important: Add your PayMongo API keys
```

Important: Never commit your `.env` file or API secret keys to version control. Use the provided `.env.example` as a template and set your keys locally or via your deployment environment.

Required environment variables:
```
PAYMONGO_SECRET_KEY=sk_test_...
PAYMONGO_PUBLIC_KEY=pk_test_...
```

On Windows PowerShell, set environment variables temporarily for a session:

```powershell
$env:PAYMONGO_SECRET_KEY = 'sk_test_...'
$env:PAYMONGO_PUBLIC_KEY = 'pk_test_...'
```

Or add them to the local `.env` file (development only). Ensure `.gitignore` contains `.env` so secrets are not committed.

### Step 5: Initialize Database

```bash
# Initialize database and create tables (including PaymentTransaction for audit logging)
python init_db.py
```

### Step 6: Run the Application

```bash
python run.py
```

The application will start and create an admin account with credentials:
- Email: admin@example.com
- Password: admin123

### Step 7 (Optional): Seed Sample Data

```bash
python seed_data.py
```

## Usage

### Access Points

- **Main Site:** http://127.0.0.1:5000
- **Admin Panel:** http://127.0.0.1:5000/admin

### Default Admin Credentials

- **Email:** admin@ticketing.com
- **Password:** admin123

> ⚠️ **Important:** Change these credentials in production!

## PayMongo Configuration

1. Create a PayMongo account at https://paymongo.com
2. Get your API keys from PayMongo Dashboard
3. Add keys to your `.env` file:
   ```
   PAYMONGO_SECRET_KEY=sk_test_...
   PAYMONGO_PUBLIC_KEY=pk_test_...
   ```

### Testing Payments

PayMongo provides test credentials for development. Use test cards, GCash, PayMaya accounts provided in their documentation.

**Supported Payment Methods:**
- Credit/Debit Cards (Visa, Mastercard, etc.)
- GCash (Philippines)
- PayMaya (Philippines)
- PayPal
- Bank Transfer

## PayMongo Integration

Full PayMongo integration is available with endpoints for:
- Payment Intents (create, retrieve, attach payment methods)
- Payment Methods (create, retrieve, update)
- Payments (retrieve, list)
- Refunds (create, retrieve, list)
- Customers (create, retrieve, update, list)

See [PAYMONGO_INTEGRATION.md](PAYMONGO_INTEGRATION.md) for comprehensive API documentation.

## Project Structure

```
flask_app/
├── app.py              # Main application with routes and models
├── config.py           # Configuration settings
├── run.py              # Application entry point
├── seed_data.py        # Sample data seeder
├── requirements.txt    # Python dependencies
├── .env.example        # Environment variables template
├── static/
│   └── uploads/        # Uploaded movie posters
└── templates/
    ├── base.html       # Base template
    ├── index.html      # Homepage
    ├── auth/           # Login/Register templates
    ├── movies/         # Movie listing and booking
    ├── bus/            # Bus search and booking
    ├── payment/        # Checkout and success pages
    ├── dashboard/      # User dashboard
    └── admin/          # Admin panel templates
```

## API Endpoints

### Public Routes
- `GET /` - Homepage
- `GET /movies` - Movie listings
- `GET /movies/<id>` - Movie details
- `GET /bus` - Bus search
- `GET /bus/search` - Bus search results

### Auth Routes
- `GET/POST /login` - User login
- `GET/POST /register` - User registration
- `GET /logout` - User logout

### Booking Routes (Login Required)
- `GET/POST /movies/<id>/book` - Book movie tickets
- `GET/POST /bus/<id>/book` - Book bus tickets
- `GET/POST /checkout/<booking_id>` - Payment checkout
- `GET /payment/success` - Payment success page
- `GET /dashboard` - User dashboard

### Admin Routes (Admin Only)
- `GET /admin` - Admin dashboard
- `GET/POST /admin/movies/add` - Add movie
- `GET/POST /admin/movies/edit/<id>` - Edit movie
- `POST /admin/movies/delete/<id>` - Delete movie
- Similar routes for cinemas, showtimes, and buses

### Payment API Routes (Admin and User)
- `POST /create-payment-intent` - Create PayMongo payment intent
- `POST /payment-ewallet-pending` - Process e-wallet payments
- `GET /check-ewallet-payment/<booking_type>/<id>` - Check payment status
- `GET /payment-success/<booking_type>/<id>` - Display success page
- `POST /webhook/paymongo` - PayMongo webhook handler

### Transaction API Routes (Admin and User)
- `GET /api/transactions` - List all transactions (admin only) 
- `GET /api/transactions/<id>` - Get transaction details (admin only)
- `GET /api/transactions/user/<user_id>` - Get user's transactions
- `GET /api/transactions/summary` - Get payment summary statistics (admin only)

### PayMongo API Routes (Admin Only)
- `POST /api/payment-intents` - Create payment intent
- `GET /api/payment-intents/<id>` - Retrieve payment intent
- `POST /api/payment-methods` - Create payment method
- `GET /api/payment-methods/<id>` - Retrieve payment method
- `GET /api/payments/<id>` - Retrieve payment
- `GET /api/payments` - List payments
- `POST /api/refunds` - Create refund
- `GET /api/refunds/<id>` - Retrieve refund
- `GET /api/refunds` - List refunds
- `POST /api/customers` - Create customer
- `GET /api/customers/<id>` - Retrieve customer
- `POST /api/customers/<id>` - Update customer
- `GET /api/customers` - List customers

## Security Features

- Password hashing with Werkzeug
- CSRF protection with Flask-WTF
- Secure session management
- Admin-only route protection
- Input validation and sanitization

## License

MIT License
