# PayMongo Integration Documentation

This document describes all PayMongo API endpoints available in the TicketHub application.

## Configuration

Ensure the following environment variables are set in your `.env` file:

```env
PAYMONGO_SECRET_KEY=sk_test_boUkkKYfbPnRVZMrVE13moQo
PAYMONGO_PUBLIC_KEY=pk_test_PA4RzhxD9BadaUFoTkaaTLbf
```

## Base URL

All endpoints are prefixed with: `http://localhost:5000`

## Authentication

Most endpoints require user authentication via Flask-Login. Admin-only endpoints are marked with `[ADMIN]`.

---

## Payment Intents

### Create Payment Intent
**POST** `/api/payment-intents`

Create a new payment intent in PayMongo.

**Request Body:**
```json
{
  "amount": 5000,
  "currency": "PHP",
  "description": "Ticket Booking",
  "metadata": {
    "booking_id": "123",
    "booking_type": "movie"
  }
}
```

**Response:**
```json
{
  "data": {
    "id": "pi_xxxxx",
    "attributes": {
      "amount": 5000,
      "currency": "PHP",
      "status": "awaiting_payment_method",
      "client_key": "pk_..."
    }
  }
}
```

### Retrieve Payment Intent
**GET** `/api/payment-intents/<intent_id>`

Retrieve details of a specific payment intent.

**Response:** Same as Create Payment Intent

### Attach Payment Method to Intent
**POST** `/api/payment-intents/<intent_id>/attach`

Attach a payment method to a payment intent.

**Request Body:**
```json
{
  "payment_method_id": "pm_xxxxx"
}
```

**Response:** Updated payment intent object

---

## Payment Methods

### Create Payment Method
**POST** `/api/payment-methods`

Create a new payment method (card, ewallet, bank_transfer).

**Request Body:**
```json
{
  "type": "card",
  "details": {
    "card_number": "4242424242424242",
    "exp_month": 12,
    "exp_year": 2025,
    "cvc": "123"
  }
}
```

Or for e-wallet:
```json
{
  "type": "gcash",
  "details": {}
}
```

**Response:**
```json
{
  "data": {
    "id": "pm_xxxxx",
    "attributes": {
      "type": "card",
      "created_at": "2024-01-01T12:00:00Z"
    }
  }
}
```

### Retrieve Payment Method
**GET** `/api/payment-methods/<method_id>`

Retrieve details of a specific payment method.

### Update Payment Method
**POST** `/api/payment-methods/<method_id>`

Update a payment method's metadata.

**Request Body:**
```json
{
  "metadata": {
    "last_used": "2024-01-01"
  }
}
```

---

## Payments

### Retrieve Payment
**GET** `/api/payments/<payment_id>`

Retrieve details of a specific payment.

**Response:**
```json
{
  "data": {
    "id": "pay_xxxxx",
    "attributes": {
      "amount": 5000,
      "currency": "PHP",
      "status": "paid",
      "description": "Ticket Order",
      "payment_method": { ... }
    }
  }
}
```

### List All Payments
**GET** `/api/payments?limit=20&after=<cursor>` [ADMIN]

List all payments with pagination.

**Query Parameters:**
- `limit` (optional): Number of results (default: 20)
- `after` (optional): Pagination cursor

**Response:**
```json
{
  "data": [ ... ],
  "pagination": {
    "has_more": false,
    "last_id": "pay_xxxxx"
  }
}
```

---

## Refunds

### Create Refund
**POST** `/api/refunds` [ADMIN]

Create a refund for a payment.

**Request Body:**
```json
{
  "payment_id": "pay_xxxxx",
  "amount": 5000,
  "reason": "customer_request",
  "notes": "Customer requested cancellation"
}
```

**Response:**
```json
{
  "data": {
    "id": "ref_xxxxx",
    "attributes": {
      "amount": 5000,
      "currency": "PHP",
      "status": "pending",
      "reason": "customer_request",
      "notes": "Customer requested cancellation"
    }
  }
}
```

### Retrieve Refund
**GET** `/api/refunds/<refund_id>` [ADMIN]

Retrieve details of a specific refund.

### List All Refunds
**GET** `/api/refunds?limit=20&after=<cursor>` [ADMIN]

List all refunds with pagination.

**Query Parameters:**
- `limit` (optional): Number of results (default: 20)
- `after` (optional): Pagination cursor

---

## Customers

### Create Customer
**POST** `/api/customers`

Create a new customer in PayMongo.

**Request Body:**
```json
{
  "email": "user@example.com",
  "phone": "+639123456789",
  "first_name": "John",
  "last_name": "Doe",
  "metadata": {
    "user_id": "123"
  }
}
```

**Response:**
```json
{
  "data": {
    "id": "cus_xxxxx",
    "attributes": {
      "email": "user@example.com",
      "phone": "+639123456789",
      "first_name": "John",
      "last_name": "Doe"
    }
  }
}
```

### Retrieve Customer
**GET** `/api/customers/<customer_id>`

Retrieve details of a specific customer.

### Update Customer
**POST** `/api/customers/<customer_id>`

Update customer information.

**Request Body:**
```json
{
  "email": "newemail@example.com",
  "phone": "+639987654321",
  "first_name": "Jane",
  "last_name": "Smith",
  "metadata": {
    "last_updated": "2024-01-01"
  }
}
```

### List All Customers
**GET** `/api/customers?limit=20&after=<cursor>` [ADMIN]

List all customers with pagination.

**Query Parameters:**
- `limit` (optional): Number of results (default: 20)
- `after` (optional): Pagination cursor

---

## E-Wallet Payment Flow

### 1. Create E-Wallet Source
**POST** `/payment-ewallet-pending`

Initialize a GCash/PayMaya/PayPal payment.

**Request Body:**
```json
{
  "booking_type": "movie",
  "booking_id": 1,
  "payment_method": "gcash"
}
```

**Response:**
```json
{
  "success": true,
  "checkout_url": "https://checkout.paymongo.com/...",
  "source_id": "src_xxxxx",
  "booking_id": 1,
  "booking_type": "movie"
}
```

### 2. User Completes Payment
- User is redirected to the `checkout_url`
- User completes payment on PayMongo's hosted page
- PayMongo returns user to redirect URL

### 3. Check Payment Status
**GET** `/check-ewallet-payment/<booking_type>/<booking_id>`

Check if a booking payment is complete.

**Response:**
```json
{
  "paid": true
}
```

### 4. Webhook Handler
**POST** `/webhook/paymongo`

PayMongo sends webhook events here. Automatically marks bookings as paid and decrements seat availability.

Configure webhook URL in PayMongo Dashboard: `https://<your-domain>/webhook/paymongo`

---

## Helper Functions

All PayMongo API calls use these helper functions defined in `app.py`:

- `pm_create_payment_intent()` - Create payment intent
- `pm_retrieve_payment_intent()` - Get payment intent
- `pm_attach_payment_method_to_intent()` - Attach payment method
- `pm_create_payment_method()` - Create payment method
- `pm_retrieve_payment_method()` - Get payment method
- `pm_update_payment_method()` - Update payment method
- `pm_create_source()` - Create source (e-wallet)
- `pm_retrieve_payment()` - Get payment
- `pm_list_payments()` - List payments
- `pm_create_refund()` - Create refund
- `pm_retrieve_refund()` - Get refund
- `pm_list_refunds()` - List refunds
- `pm_create_customer()` - Create customer
- `pm_retrieve_customer()` - Get customer
- `pm_update_customer()` - Update customer
- `pm_list_customers()` - List customers

---

## Error Handling

All endpoints return error responses in this format:

```json
{
  "error": "Error message here"
}
```

HTTP Status Codes:
- `200` - Success
- `400` - Bad Request (validation error)
- `404` - Not Found
- `500` - Server Error

---

## Testing

### Using cURL

```bash
# Create a payment intent
curl -X POST http://localhost:5000/api/payment-intents \
  -H "Content-Type: application/json" \
  -d '{
    "amount": 5000,
    "currency": "PHP",
    "description": "Test Payment"
  }' \
  -b "session=<your_session_cookie>"

# List payments (admin only)
curl -X GET "http://localhost:5000/api/payments?limit=10" \
  -H "Authorization: Bearer <token>" \
  -b "session=<your_admin_session>"
```

### Using Python Requests

```python
import requests

headers = {
    "Content-Type": "application/json"
}
cookies = {"session": "<your_session_cookie>"}

# Create payment intent
response = requests.post(
    'http://localhost:5000/api/payment-intents',
    json={
        "amount": 5000,
        "currency": "PHP",
        "description": "Test Payment"
    },
    headers=headers,
    cookies=cookies
)

payment_intent = response.json()
print(payment_intent)
```

---

## Payment Transaction Logs

The system maintains a comprehensive audit trail of all payment transactions in the `PaymentTransaction` table. This allows administrators and users to track payment history and reconcile transactions.

### PaymentTransaction Model

```python
class PaymentTransaction(db.Model):
    id              # Primary key
    user_id         # Foreign key to User
    booking_type    # 'movie' or 'bus'
    booking_id      # ID of the booking
    booking_reference  # Booking reference code
    amount          # Transaction amount in PHP
    currency        # Currency code (default: 'PHP')
    payment_method  # 'card', 'gcash', 'paymaya', 'paypal'
    payment_status  # 'pending', 'completed', 'failed'
    payment_source_id  # PayMongo source ID
    payment_intent_id  # PayMongo payment intent ID
    error_message   # Error details (if failed)
    transaction_metadata  # JSON field for additional data
    created_at      # Transaction creation timestamp
    updated_at      # Last update timestamp
```

### List All Transactions (Admin Only)
**GET** `/api/transactions`

Retrieve a paginated list of all payment transactions.

**Query Parameters:**
- `page` (int, default: 1) - Page number
- `per_page` (int, default: 50) - Records per page
- `user_id` (int, optional) - Filter by user
- `booking_type` (string, optional) - Filter by 'movie' or 'bus'
- `status` (string, optional) - Filter by 'pending', 'completed', or 'failed'

**Response:**
```json
{
  "transactions": [
    {
      "id": 1,
      "user_id": 5,
      "booking_type": "movie",
      "booking_reference": "MOVIE-20240308-001",
      "amount": 500.00,
      "payment_method": "gcash",
      "payment_status": "completed",
      "source_id": "src_xxxxx",
      "created_at": "2024-03-08T10:30:00",
      "updated_at": "2024-03-08T10:32:00"
    }
  ],
  "total": 150,
  "pages": 3,
  "current_page": 1
}
```

### Get Transaction Details (Admin Only)
**GET** `/api/transactions/<transaction_id>`

Retrieve complete details of a specific transaction including error messages if any.

**Response:**
```json
{
  "id": 1,
  "user_id": 5,
  "booking_type": "movie",
  "booking_id": 42,
  "booking_reference": "MOVIE-20240308-001",
  "amount": 500.00,
  "currency": "PHP",
  "payment_method": "gcash",
  "payment_status": "completed",
  "source_id": "src_xxxxx",
  "intent_id": "pi_xxxxx",
  "error_message": null,
  "created_at": "2024-03-08T10:30:00",
  "updated_at": "2024-03-08T10:32:00"
}
```

### Get User Transactions
**GET** `/api/transactions/user/<user_id>`

Retrieve paginated transaction history for a specific user. Users can only view their own transactions unless they are admins.

**Query Parameters:**
- `page` (int, default: 1) - Page number
- `per_page` (int, default: 20) - Records per page

**Response:**
```json
{
  "transactions": [
    {
      "id": 1,
      "booking_type": "movie",
      "booking_reference": "MOVIE-20240308-001",
      "amount": 500.00,
      "payment_method": "gcash",
      "payment_status": "completed",
      "created_at": "2024-03-08T10:30:00"
    }
  ],
  "total": 25,
  "pages": 2,
  "current_page": 1
}
```

### Get Transaction Summary (Admin Only)
**GET** `/api/transactions/summary`

Retrieve overall payment statistics and analytics.

**Response:**
```json
{
  "total_transactions": 250,
  "total_amount": 125000.00,
  "by_status": {
    "completed": 245,
    "pending": 3,
    "failed": 2
  },
  "by_method": {
    "card": {
      "count": 120,
      "amount": 60000.00
    },
    "gcash": {
      "count": 80,
      "amount": 40000.00
    },
    "paymaya": {
      "count": 35,
      "amount": 17500.00
    },
    "paypal": {
      "count": 15,
      "amount": 7500.00
    }
  }
}
```

## Database Initialization

To set up the database with all required tables (including `PaymentTransaction`), run:

```bash
python init_db.py
```

This creates all tables defined in the SQLAlchemy models.

---

## Notes

- All amounts are in centavos (multiply PHP amounts by 100)
- Currency defaults to PHP
- E-wallet payments are instant redirects to PayMongo's hosted page
- Card payments may require additional authentication (3D Secure)
- Refunds must be initiated by admin users
- Webhooks must be configured in PayMongo Dashboard for automatic status updates
- Customer records are optional but recommended for subscription or recurring payments
- Transaction logs are automatically created for all payment attempts (pending, completed, or failed)
- The `PaymentTransaction` table provides a complete audit trail for payment reconciliation
