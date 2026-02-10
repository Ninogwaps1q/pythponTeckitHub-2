#!/usr/bin/env python
"""
Database initialization script
Creates or updates database schema with all required tables
"""
import os
from app import app, db

def init_database():
    """Initialize database with all tables"""
    with app.app_context():
        # Create database directory if it doesn't exist
        instance_path = 'instance'
        if not os.path.exists(instance_path):
            os.makedirs(instance_path)
        
        print("\n" + "="*50)
        print("Initializing Database...")
        print("="*50)
        
        # Create all tables
        db.create_all()
        
        print("\n✓ Database tables created/updated successfully!")
        print("\nTables created:")
        print("  - User")
        print("  - Movie")
        print("  - Cinema")
        print("  - Showtime")
        print("  - MovieBooking")
        print("  - Bus")
        print("  - BusRoute")
        print("  - BusSchedule")
        print("  - BusBooking")
        print("  - PaymentTransaction (NEW)")
        
        print("\n" + "="*50)
        print("Next steps:")
        print("  1. Run 'python seed_data.py' to add sample data")
        print("  2. Run 'python run.py' to start the application")
        print("="*50 + "\n")

if __name__ == '__main__':
    init_database()
