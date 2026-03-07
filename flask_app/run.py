#!/usr/bin/env python
"""
Run script for the Movie + Bus Ticketing Application
"""
import os
from app import app, db, User, ensure_booking_verification_columns
from werkzeug.security import generate_password_hash

def create_admin():
    """Create default admin user if it doesn't exist"""
    with app.app_context():
        admin = User.query.filter_by(email='admin@ticketing.com').first()
        if not admin:
            admin = User(
                name='Administrator',
                email='admin@ticketing.com',
                password=generate_password_hash('admin123'),
                is_admin=True
            )
            db.session.add(admin)
            db.session.commit()
            print("Admin user created successfully!")
            print("Email: admin@ticketing.com")
            print("Password: admin123")
        else:
            print("Admin user already exists.")

def init_db():
    """Initialize the database"""
    with app.app_context():
        db.create_all()
        ensure_booking_verification_columns()
        print("Database tables created successfully!")

if __name__ == '__main__':
    # Create upload directory if it doesn't exist
    upload_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads')
    os.makedirs(upload_dir, exist_ok=True)
    
    # Initialize database and create admin
    init_db()
    create_admin()
    
    # Run the application
    print("\n" + "="*50)
    print("Movie + Bus Ticketing Application")
    print("="*50)
    print("Running on: http://127.0.0.1:5000")
    print("Admin Panel: http://127.0.0.1:5000/admin")
    print("="*50 + "\n")
    
    app.run(debug=True, host='0.0.0.0', port=5000)
