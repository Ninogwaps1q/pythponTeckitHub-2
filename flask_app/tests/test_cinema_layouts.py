import unittest

try:
    from flask_app.app import (
        Cinema,
        Showtime,
        build_cinema_seat_layout,
        movie_seat_list_to_display,
        normalize_movie_seat_code,
        summarize_movie_booking_selection,
    )
except ModuleNotFoundError:
    from app import (
        Cinema,
        Showtime,
        build_cinema_seat_layout,
        movie_seat_list_to_display,
        normalize_movie_seat_code,
        summarize_movie_booking_selection,
    )


class CinemaLayoutTests(unittest.TestCase):
    def build_showtime(self, seat_layout_style='classic', total_seats=20, vip_rows=1, vip_surcharge=120.0, price=250.0):
        cinema = Cinema(
            name='Cinema Test',
            location='Downtown',
            total_seats=total_seats,
            seat_layout_style=seat_layout_style,
            vip_rows=vip_rows,
            vip_surcharge=vip_surcharge,
        )
        showtime = Showtime(price=price, available_seats=total_seats)
        showtime.cinema = cinema
        return showtime

    def test_normalize_movie_seat_code_accepts_display_style_labels(self):
        self.assertEqual(normalize_movie_seat_code('A1'), '1-1')
        self.assertEqual(normalize_movie_seat_code('c7'), '3-7')
        self.assertEqual(normalize_movie_seat_code('2-5'), '2-5')

    def test_build_cinema_seat_layout_uses_selected_style_and_marks_vip_rows(self):
        showtime = self.build_showtime(seat_layout_style='stadium', total_seats=24, vip_rows=1, vip_surcharge=150.0)

        layout = build_cinema_seat_layout(showtime)

        self.assertEqual(layout['style'], 'stadium')
        self.assertEqual(layout['row_capacity'], 12)
        self.assertEqual(len(layout['seat_codes']), 24)
        self.assertEqual(layout['vip_rows'], 1)
        self.assertIn('2-1', layout['vip_seats'])
        self.assertNotIn('1-1', layout['vip_seats'])
        self.assertEqual(layout['rows'][1]['offset_units'], 0)

    def test_summarize_movie_booking_selection_adds_vip_surcharge(self):
        showtime = self.build_showtime(seat_layout_style='luxe', total_seats=16, vip_rows=1, vip_surcharge=150.0, price=200.0)

        summary = summarize_movie_booking_selection(showtime, ['1-1', 'B2'])

        self.assertEqual(summary['ticket_count'], 2)
        self.assertEqual(summary['regular_count'], 1)
        self.assertEqual(summary['vip_count'], 1)
        self.assertEqual(summary['selected_labels'], ['A1', 'B2'])
        self.assertEqual(summary['total_amount'], 550.0)

    def test_premiere_layout_is_available_for_cinema_specific_designs(self):
        showtime = self.build_showtime(seat_layout_style='premiere', total_seats=24, vip_rows=2, vip_surcharge=180.0)

        layout = build_cinema_seat_layout(showtime)

        self.assertEqual(layout['style'], 'premiere')
        self.assertEqual(layout['row_capacity'], 8)
        self.assertEqual(layout['style_label'], 'Premiere Suite')
        self.assertIn('2-1', layout['vip_seats'])
        self.assertIn('3-8', layout['vip_seats'])
        self.assertNotIn('1-1', layout['vip_seats'])

    def test_movie_seat_list_to_display_remains_backward_compatible(self):
        self.assertEqual(movie_seat_list_to_display('1-1,2-3'), 'A1, B3')
        self.assertEqual(movie_seat_list_to_display('A1,B3'), 'A1, B3')


if __name__ == '__main__':
    unittest.main()
