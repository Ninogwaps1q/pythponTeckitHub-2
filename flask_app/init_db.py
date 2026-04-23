#!/usr/bin/env python
"""
Database initialization script.
Creates or updates database schema with all required tables.
"""

import os

try:
    from app import app, db
except ModuleNotFoundError:
    from flask_app.app import app, db


def init_database():
    """Initialize database with all tables."""
    with app.app_context():
        instance_path = 'instance'
        if not os.path.exists(instance_path):
            os.makedirs(instance_path)

        print("\n" + "=" * 50)
        print("Initializing Database...")
        print("=" * 50)

        db.drop_all()
        db.create_all()

        print("\nDatabase tables created/updated successfully!")
        print("\nTables created:")
        print("  - User")
        print("  - Movie")
        print("  - Cinema")
        print("  - Showtime")
        print("  - MovieBooking")
        print("  - BusRoute")
        print("  - BusSchedule")
        print("  - BusBooking")
        print("  - PaymentTransaction")

        print("\n" + "=" * 50)
        print("Next steps:")
        print("  1. Run 'python seed_data.py' to add sample data")
        print("  2. Run 'python run.py' to start the application")
        print("=" * 50 + "\n")


if __name__ == '__main__':
    init_database()
