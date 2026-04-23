import unittest

try:
    from flask_app.status_utils import normalize_payment_status, payment_status_badge_class, payment_status_label
except ModuleNotFoundError:
    from status_utils import normalize_payment_status, payment_status_badge_class, payment_status_label


class StatusUtilsTests(unittest.TestCase):
    def test_normalize_payment_status_maps_success_aliases(self):
        self.assertEqual(normalize_payment_status('captured'), 'paid')
        self.assertEqual(normalize_payment_status('succeeded'), 'paid')

    def test_payment_status_label_and_badge(self):
        self.assertEqual(payment_status_label('refund_pending'), 'Refund Pending')
        self.assertEqual(payment_status_badge_class('failed'), 'danger')


if __name__ == '__main__':
    unittest.main()
