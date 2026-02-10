#!/usr/bin/env python
"""
Seed script to populate the database with sample data
"""
from datetime import datetime, timedelta
from app import app, db, Movie, Cinema, Showtime, Bus

def seed_movies():
    """Add sample movies"""
    movies = [
        {
            'title': 'Galactic Adventures',
            'description': 'An epic space odyssey that takes you to the far reaches of the universe. Follow Captain Nova as she leads her crew through uncharted territories.',
            'genre': 'Sci-Fi',
            'duration': 148,
            'rating': 'PG-13',
            'release_date': datetime(2024, 1, 15),
            'director': 'James Cameron',
            'cast': 'Sarah Connor, John Smith, Emma Watson'
        },
        {
            'title': 'The Last Kingdom',
            'description': 'A medieval epic about honor, betrayal, and the fight for freedom. King Arthur must unite the kingdoms against a common enemy.',
            'genre': 'Action',
            'duration': 165,
            'rating': 'R',
            'release_date': datetime(2024, 2, 20),
            'director': 'Ridley Scott',
            'cast': 'Chris Hemsworth, Cate Blanchett'
        },
        {
            'title': 'Love in Paris',
            'description': 'A heartwarming romantic comedy set in the beautiful streets of Paris. Two strangers meet by chance and discover love.',
            'genre': 'Romance',
            'duration': 112,
            'rating': 'PG',
            'release_date': datetime(2024, 2, 14),
            'director': 'Nancy Meyers',
            'cast': 'Emily Blunt, Ryan Gosling'
        },
        {
            'title': 'Midnight Terror',
            'description': 'A terrifying horror experience that will keep you on the edge of your seat. Something sinister lurks in the darkness.',
            'genre': 'Horror',
            'duration': 98,
            'rating': 'R',
            'release_date': datetime(2024, 3, 1),
            'director': 'Jordan Peele',
            'cast': 'Lupita Nyongo, Daniel Kaluuya'
        },
        {
            'title': 'The Comedy Club',
            'description': 'A hilarious ensemble comedy about a group of friends who start a comedy club. Laughs guaranteed!',
            'genre': 'Comedy',
            'duration': 105,
            'rating': 'PG-13',
            'release_date': datetime(2024, 3, 15),
            'director': 'Judd Apatow',
            'cast': 'Steve Carell, Tina Fey, Kevin Hart'
        }
    ]
    
    for movie_data in movies:
        existing = Movie.query.filter_by(title=movie_data['title']).first()
        if not existing:
            movie = Movie(**movie_data)
            db.session.add(movie)
    
    db.session.commit()
    print(f"Added {len(movies)} movies")

def seed_cinemas():
    """Add sample cinemas"""
    cinemas = [
        {'name': 'Cineplex Downtown', 'location': '123 Main Street, Downtown', 'total_seats': 150},
        {'name': 'Star Cinema Mall', 'location': '456 Shopping Avenue, Westside', 'total_seats': 200},
        {'name': 'IMAX Experience', 'location': '789 Tech Boulevard, Eastside', 'total_seats': 300},
        {'name': 'Classic Theater', 'location': '321 Heritage Lane, Old Town', 'total_seats': 100},
    ]
    
    for cinema_data in cinemas:
        existing = Cinema.query.filter_by(name=cinema_data['name']).first()
        if not existing:
            cinema = Cinema(**cinema_data)
            db.session.add(cinema)
    
    db.session.commit()
    print(f"Added {len(cinemas)} cinemas")

def seed_showtimes():
    """Add sample showtimes"""
    movies = Movie.query.all()
    cinemas = Cinema.query.all()
    
    if not movies or not cinemas:
        print("No movies or cinemas found. Please seed them first.")
        return
    
    times = ['10:00', '13:30', '16:00', '19:00', '21:30']
    prices = [12.99, 14.99, 14.99, 16.99, 16.99]
    
    count = 0
    for movie in movies:
        for cinema in cinemas[:2]:  # Only use first 2 cinemas for variety
            for i, time in enumerate(times):
                for day_offset in range(7):  # Next 7 days
                    show_date = datetime.now().date() + timedelta(days=day_offset)
                    show_datetime = datetime.combine(show_date, datetime.strptime(time, '%H:%M').time())
                    
                    existing = Showtime.query.filter_by(
                        movie_id=movie.id,
                        cinema_id=cinema.id,
                        show_datetime=show_datetime
                    ).first()
                    
                    if not existing:
                        showtime = Showtime(
                            movie_id=movie.id,
                            cinema_id=cinema.id,
                            show_datetime=show_datetime,
                            price=prices[i],
                            available_seats=cinema.total_seats
                        )
                        db.session.add(showtime)
                        count += 1
    
    db.session.commit()
    print(f"Added {count} showtimes")

def seed_buses():
    """Add sample bus routes"""
    buses = [
        {
            'bus_name': 'Express Liner 101',
            'bus_type': 'Luxury',
            'origin': 'New York',
            'destination': 'Boston',
            'departure_time': datetime.strptime('08:00', '%H:%M').time(),
            'arrival_time': datetime.strptime('12:30', '%H:%M').time(),
            'price': 45.00,
            'total_seats': 40,
            'available_seats': 40,
            'amenities': 'WiFi, AC, USB Charging, Reclining Seats'
        },
        {
            'bus_name': 'City Connect 202',
            'bus_type': 'Standard',
            'origin': 'New York',
            'destination': 'Philadelphia',
            'departure_time': datetime.strptime('09:30', '%H:%M').time(),
            'arrival_time': datetime.strptime('11:30', '%H:%M').time(),
            'price': 25.00,
            'total_seats': 50,
            'available_seats': 50,
            'amenities': 'AC, Reading Light'
        },
        {
            'bus_name': 'Night Owl 303',
            'bus_type': 'Sleeper',
            'origin': 'New York',
            'destination': 'Washington DC',
            'departure_time': datetime.strptime('23:00', '%H:%M').time(),
            'arrival_time': datetime.strptime('04:30', '%H:%M').time(),
            'price': 55.00,
            'total_seats': 30,
            'available_seats': 30,
            'amenities': 'WiFi, AC, Sleeper Berths, Blankets, Pillow'
        },
        {
            'bus_name': 'Budget Traveler 404',
            'bus_type': 'Non-AC',
            'origin': 'Boston',
            'destination': 'New York',
            'departure_time': datetime.strptime('07:00', '%H:%M').time(),
            'arrival_time': datetime.strptime('11:30', '%H:%M').time(),
            'price': 20.00,
            'total_seats': 45,
            'available_seats': 45,
            'amenities': 'Basic Seating'
        },
        {
            'bus_name': 'Premium Plus 505',
            'bus_type': 'Luxury',
            'origin': 'Philadelphia',
            'destination': 'Washington DC',
            'departure_time': datetime.strptime('10:00', '%H:%M').time(),
            'arrival_time': datetime.strptime('13:00', '%H:%M').time(),
            'price': 65.00,
            'total_seats': 25,
            'available_seats': 25,
            'amenities': 'WiFi, AC, USB Charging, Snacks, Entertainment System'
        },
        {
            'bus_name': 'Morning Express 606',
            'bus_type': 'AC',
            'origin': 'Washington DC',
            'destination': 'New York',
            'departure_time': datetime.strptime('06:00', '%H:%M').time(),
            'arrival_time': datetime.strptime('10:30', '%H:%M').time(),
            'price': 40.00,
            'total_seats': 40,
            'available_seats': 40,
            'amenities': 'WiFi, AC, USB Charging'
        },
    ]
    
    for bus_data in buses:
        existing = Bus.query.filter_by(bus_name=bus_data['bus_name']).first()
        if not existing:
            bus = Bus(**bus_data)
            db.session.add(bus)
    
    db.session.commit()
    print(f"Added {len(buses)} bus routes")

def seed_all():
    """Seed all sample data"""
    with app.app_context():
        print("\nSeeding database with sample data...")
        print("-" * 40)
        seed_movies()
        seed_cinemas()
        seed_showtimes()
        seed_buses()
        print("-" * 40)
        print("Sample data seeded successfully!\n")

if __name__ == '__main__':
    seed_all()
