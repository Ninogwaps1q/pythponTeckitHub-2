#!/usr/bin/env python
"""
Seed script to populate the database with sample data.
"""

from datetime import date, datetime, timedelta

try:
    from app import app, db, Movie, Cinema, Showtime, BusRoute, BusSchedule
except ModuleNotFoundError:
    from flask_app.app import app, db, Movie, Cinema, Showtime, BusRoute, BusSchedule


def seed_movies():
    """Add sample movies."""
    movies = [
        {
            'title': 'Galactic Adventures',
            'description': 'An epic space odyssey that pushes a crew into uncharted space.',
            'genre': 'Sci-Fi',
            'duration': 148,
            'rating': 'PG-13',
            'release_date': date(2024, 1, 15),
        },
        {
            'title': 'The Last Kingdom',
            'description': 'A medieval epic about honor, betrayal, and survival.',
            'genre': 'Action',
            'duration': 165,
            'rating': 'R',
            'release_date': date(2024, 2, 20),
        },
        {
            'title': 'Love in Paris',
            'description': 'A romantic comedy about two strangers meeting by chance.',
            'genre': 'Romance',
            'duration': 112,
            'rating': 'PG',
            'release_date': date(2024, 2, 14),
        },
        {
            'title': 'Midnight Terror',
            'description': 'A horror story about something sinister hiding in the dark.',
            'genre': 'Horror',
            'duration': 98,
            'rating': 'R',
            'release_date': date(2024, 3, 1),
        },
        {
            'title': 'The Comedy Club',
            'description': 'A comedy about friends building a stand-up venue from scratch.',
            'genre': 'Comedy',
            'duration': 105,
            'rating': 'PG-13',
            'release_date': date(2024, 3, 15),
        },
    ]

    added = 0
    for movie_data in movies:
        existing = Movie.query.filter_by(title=movie_data['title']).first()
        if not existing:
            db.session.add(Movie(**movie_data))
            added += 1

    db.session.commit()
    print(f"Added {added} movies")


def seed_cinemas():
    """Add sample cinemas."""
    cinemas = [
        {'name': 'Cineplex Downtown', 'location': '123 Main Street, Downtown', 'total_seats': 150},
        {'name': 'Star Cinema Mall', 'location': '456 Shopping Avenue, Westside', 'total_seats': 200},
        {'name': 'IMAX Experience', 'location': '789 Tech Boulevard, Eastside', 'total_seats': 300},
        {'name': 'Classic Theater', 'location': '321 Heritage Lane, Old Town', 'total_seats': 100},
    ]

    added = 0
    for cinema_data in cinemas:
        existing = Cinema.query.filter_by(name=cinema_data['name']).first()
        if not existing:
            db.session.add(Cinema(**cinema_data))
            added += 1

    db.session.commit()
    print(f"Added {added} cinemas")


def seed_showtimes(days=7):
    """Add sample showtimes for the next few days."""
    movies = Movie.query.all()
    cinemas = Cinema.query.all()

    if not movies or not cinemas:
        print("No movies or cinemas found. Please seed them first.")
        return

    time_slots = [('10:00', 250.0), ('13:30', 280.0), ('16:00', 300.0), ('19:00', 320.0), ('21:30', 300.0)]

    count = 0
    for movie in movies:
        for cinema in cinemas[:2]:
            for time_text, price in time_slots:
                show_time = datetime.strptime(time_text, '%H:%M').time()
                for day_offset in range(days):
                    show_date = datetime.now().date() + timedelta(days=day_offset)
                    existing = Showtime.query.filter_by(
                        movie_id=movie.id,
                        cinema_id=cinema.id,
                        show_date=show_date,
                        show_time=show_time,
                    ).first()

                    if not existing:
                        db.session.add(
                            Showtime(
                                movie_id=movie.id,
                                cinema_id=cinema.id,
                                show_date=show_date,
                                show_time=show_time,
                                price=price,
                                available_seats=cinema.total_seats,
                            )
                        )
                        count += 1

    db.session.commit()
    print(f"Added {count} showtimes")


def seed_buses():
    """Add sample bus routes."""
    routes = [
        {
            'bus_number': 'EXP-101',
            'origin': 'Manila',
            'destination': 'Baguio',
            'departure_time': '08:00',
            'arrival_time': '12:30',
            'duration': '4h 30m',
            'price': 650.0,
            'total_seats': 40,
            'bus_type': 'Luxury',
            'amenities': 'WiFi, AC, USB Charging, Reclining Seats',
        },
        {
            'bus_number': 'CTY-202',
            'origin': 'Manila',
            'destination': 'Batangas',
            'departure_time': '09:30',
            'arrival_time': '11:30',
            'duration': '2h',
            'price': 280.0,
            'total_seats': 50,
            'bus_type': 'Standard',
            'amenities': 'AC, Reading Light',
        },
        {
            'bus_number': 'NTL-303',
            'origin': 'Manila',
            'destination': 'Naga',
            'departure_time': '23:00',
            'arrival_time': '06:00',
            'duration': '7h',
            'price': 950.0,
            'total_seats': 30,
            'bus_type': 'Sleeper',
            'amenities': 'WiFi, AC, Sleeper Berths, Blankets, Pillow',
        },
        {
            'bus_number': 'BDG-404',
            'origin': 'Baguio',
            'destination': 'Manila',
            'departure_time': '07:00',
            'arrival_time': '11:30',
            'duration': '4h 30m',
            'price': 520.0,
            'total_seats': 45,
            'bus_type': 'Non-AC',
            'amenities': 'Basic Seating',
        },
    ]

    added = 0
    for route_data in routes:
        existing = BusRoute.query.filter_by(
            bus_number=route_data['bus_number'],
            origin=route_data['origin'],
            destination=route_data['destination'],
        ).first()
        if existing:
            continue

        db.session.add(
            BusRoute(
                bus_number=route_data['bus_number'],
                origin=route_data['origin'],
                destination=route_data['destination'],
                departure_time=datetime.strptime(route_data['departure_time'], '%H:%M').time(),
                arrival_time=datetime.strptime(route_data['arrival_time'], '%H:%M').time(),
                duration=route_data['duration'],
                price=route_data['price'],
                total_seats=route_data['total_seats'],
                bus_type=route_data['bus_type'],
                amenities=route_data['amenities'],
                is_active=True,
            )
        )
        added += 1

    db.session.commit()
    print(f"Added {added} bus routes")


def seed_bus_schedules(days=7):
    """Add sample schedules for each route."""
    routes = BusRoute.query.all()
    if not routes:
        print("No bus routes found. Please seed them first.")
        return

    count = 0
    for route in routes:
        for day_offset in range(days):
            travel_date = datetime.now().date() + timedelta(days=day_offset)
            existing = BusSchedule.query.filter_by(route_id=route.id, travel_date=travel_date).first()
            if existing:
                continue

            db.session.add(
                BusSchedule(
                    route_id=route.id,
                    travel_date=travel_date,
                    available_seats=route.total_seats,
                )
            )
            count += 1

    db.session.commit()
    print(f"Added {count} bus schedules")


def seed_all():
    """Seed all sample data."""
    with app.app_context():
        print("\nSeeding database with sample data...")
        print("-" * 40)
        seed_movies()
        seed_cinemas()
        seed_showtimes()
        seed_buses()
        seed_bus_schedules()
        print("-" * 40)
        print("Sample data seeded successfully!\n")


if __name__ == '__main__':
    seed_all()
