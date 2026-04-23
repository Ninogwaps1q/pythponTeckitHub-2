import tempfile
import unittest
from datetime import date, time
from pathlib import Path

from flask import Flask

try:
    from flask_app.app import (
        BusBooking,
        BusRoute,
        BusSchedule,
        Cinema,
        Movie,
        MovieBooking,
        Showtime,
        User,
        db,
    )
except ModuleNotFoundError:
    from app import (
        BusBooking,
        BusRoute,
        BusSchedule,
        Cinema,
        Movie,
        MovieBooking,
        Showtime,
        User,
        db,
    )


class DeleteCascadeTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tempdir.name) / 'delete-cascade.db'

        self.test_app = Flask(__name__)
        self.test_app.config.update(
            SECRET_KEY='test-secret',
            SQLALCHEMY_DATABASE_URI=f"sqlite:///{db_path}",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
        )

        db.init_app(self.test_app)
        self.app_context = self.test_app.app_context()
        self.app_context.push()
        db.create_all()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()
        self.tempdir.cleanup()

    def test_deleting_movie_cascades_showtimes_and_bookings(self):
        user = User(email='movie@example.com', password_hash='hash', name='Movie User')
        cinema = Cinema(name='Cinema 1', location='Downtown', total_seats=80)
        movie = Movie(title='Delete Me')

        db.session.add_all([user, cinema, movie])
        db.session.commit()

        showtime = Showtime(
            movie_id=movie.id,
            cinema_id=cinema.id,
            show_date=date(2026, 4, 23),
            show_time=time(19, 30),
            price=250.0,
            available_seats=80,
        )
        db.session.add(showtime)
        db.session.commit()

        booking = MovieBooking(
            user_id=user.id,
            showtime_id=showtime.id,
            num_tickets=2,
            seat_numbers='A1,A2',
            total_amount=500.0,
            booking_reference='MOV-DELETE-1',
        )
        db.session.add(booking)
        db.session.commit()

        db.session.delete(movie)
        db.session.commit()

        self.assertEqual(Movie.query.count(), 0)
        self.assertEqual(Showtime.query.count(), 0)
        self.assertEqual(MovieBooking.query.count(), 0)

    def test_deleting_bus_route_cascades_schedules_and_bookings(self):
        user = User(email='bus@example.com', password_hash='hash', name='Bus User')
        route = BusRoute(
            origin='City A',
            destination='City B',
            bus_number='BUS-101',
            bus_type='AC',
            departure_time=time(8, 0),
            arrival_time=time(10, 0),
            duration='2h',
            price=150.0,
            total_seats=40,
        )

        db.session.add_all([user, route])
        db.session.commit()

        schedule = BusSchedule(
            route_id=route.id,
            travel_date=date(2026, 4, 24),
            available_seats=40,
        )
        db.session.add(schedule)
        db.session.commit()

        booking = BusBooking(
            user_id=user.id,
            schedule_id=schedule.id,
            num_tickets=1,
            seat_numbers='1A',
            passenger_names='Bus User',
            total_amount=150.0,
            booking_reference='BUS-DELETE-1',
        )
        db.session.add(booking)
        db.session.commit()

        db.session.delete(route)
        db.session.commit()

        self.assertEqual(BusRoute.query.count(), 0)
        self.assertEqual(BusSchedule.query.count(), 0)
        self.assertEqual(BusBooking.query.count(), 0)


if __name__ == '__main__':
    unittest.main()
