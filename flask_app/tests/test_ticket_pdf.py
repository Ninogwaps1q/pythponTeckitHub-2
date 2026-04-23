import unittest

try:
    from flask_app.ticket_pdf import build_simple_pdf
except ModuleNotFoundError:
    from ticket_pdf import build_simple_pdf


class TicketPdfTests(unittest.TestCase):
    def test_simple_pdf_starts_with_pdf_header(self):
        pdf_bytes = build_simple_pdf('Ticket', ['Booking Reference: ABC123'])
        self.assertTrue(pdf_bytes.startswith(b'%PDF-1.4'))


if __name__ == '__main__':
    unittest.main()
