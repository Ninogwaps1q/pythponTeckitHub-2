#!/usr/bin/env python
"""
Database Migration Guide
Upgrading from previous schema to new PaymentTransaction table

IMPORTANT: This migration removes the deprecated stripe_payment_id column
and adds the new PaymentTransaction table for payment audit logging.
"""

# Changes Applied:
# 1. REMOVED: stripe_payment_id column from MovieBooking model
# 2. REMOVED: stripe_payment_id column from BusBooking model
# 3. ADDED: PaymentTransaction model with comprehensive transaction logging
# 4. UPDATED: Payment endpoints to log transactions
# 5. UPDATED: Webhook handler to log payment completions/failures
# 6. ADDED: Transaction API endpoints for querying payment history

# Migration Steps:

# For Fresh Deployment (Recommended):
# 1. Delete the existing database file (instance/ticketing.db)
# 2. Run: python init_db.py
# 3. Run: python seed_data.py (optional, for sample data)
# 4. Run: python run.py

# For Existing Deployments:
# If you have existing data and want to preserve MovieBooking/BusBooking records:

# Option 1: Automatic (RECOMMENDED)
# 1. Backup your database: cp instance/ticketing.db instance/ticketing.db.backup
# 2. Delete the database: rm instance/ticketing.db
# 3. Run: python init_db.py
# 4. Re-seed your data using your backup or manual process

# Option 2: Manual SQLite Migrations
# These SQL commands can be run directly on SQLite if you want to preserve data:
# Note: SQLite doesn't support dropping columns easily, so the above options are better

# Schema Changes:

# OLD MovieBooking:
# - stripe_payment_id (REMOVED)
# - payment_reference (preserved)
# - payment_method (preserved)
# - payment_status (preserved)

# NEW MovieBooking:
# - payment_reference (preserved)
# - payment_method (preserved)
# - payment_status (preserved)
# (stripe_payment_id completely removed)

# NEW PaymentTransaction (ADDED):
"""
Schema:
- id (Primary Key)
- user_id (Foreign Key -> User)
- booking_type (STRING: 'movie' or 'bus')
- booking_id (INTEGER)
- booking_reference (STRING)
- amount (FLOAT)
- currency (STRING, default 'PHP')
- payment_method (STRING: 'card', 'gcash', 'paymaya', 'paypal')
- payment_status (STRING: 'pending', 'completed', 'failed')
- payment_source_id (STRING, nullable)
- payment_intent_id (STRING, nullable)
- error_message (TEXT, nullable)
- metadata (JSON, nullable)
- created_at (DATETIME)
- updated_at (DATETIME)
"""

# Migration Verification:

# After running init_db.py, verify the changes:
# 1. Check that MovieBooking doesn't have stripe_payment_id column
# 2. Check that BusBooking doesn't have stripe_payment_id column
# 3. Check that PaymentTransaction table exists with all columns
# 4. Verify that new payment endpoints log transactions

# Testing:

# 1. Make a test booking
# 2. Attempt a payment (it will be logged in PaymentTransaction)
# 3. Check: GET /api/transactions/summary
# 4. Check: GET /api/transactions/user/<user_id>
# 5. Verify transaction shows up with correct payment_method

# Code Changes Made:

# In app.py:
# - Removed stripe_payment_id from MovieBooking model (line 348)
# - Removed stripe_payment_id from BusBooking model (line 395)
# - Added PaymentTransaction model (new)
# - Added log_payment_transaction() function (new)
# - Updated payment endpoints to call log_payment_transaction()
# - Updated webhook handler to log transactions
# - Added 4 new API endpoints for transaction queries

# In config.py:
# - Removed STRIPE_PUBLIC_KEY, STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET
# - Added PAYMONGO_SECRET_KEY, PAYMONGO_PUBLIC_KEY

# In .env and .env.example:
# - Replaced Stripe keys with PayMongo keys

# In app.py docstring:
# - Updated description from Stripe to PayMongo

# Success Indicators:

# After migration, you should see:
# 1. No references to stripe_payment_id in the code (except comments)
# 2. PaymentTransaction table with sample entries from new payments
# 3. All payment methods (card, gcash, paymaya, paypal) logging correctly
# 4. Transaction summary API working and showing statistics

print(__doc__)
