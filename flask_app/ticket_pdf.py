"""Simple pure-Python ticket PDF builder."""

from datetime import datetime


def _escape_pdf_text(value):
    text = str(value or '')
    return text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')


def build_simple_pdf(title, lines):
    safe_lines = [str(line or '').strip() for line in lines if str(line or '').strip()]
    content_lines = [
        'BT',
        '/F1 18 Tf',
        '50 790 Td',
        f'({_escape_pdf_text(title)}) Tj',
        '0 -26 Td',
        '/F1 11 Tf',
    ]

    for line in safe_lines:
        content_lines.append(f'({_escape_pdf_text(line)}) Tj')
        content_lines.append('0 -16 Td')

    content_lines.append('ET')
    content_stream = '\n'.join(content_lines).encode('latin-1', errors='replace')

    objects = []
    objects.append(b'1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj')
    objects.append(b'2 0 obj << /Type /Pages /Count 1 /Kids [3 0 R] >> endobj')
    objects.append(
        b'3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] '
        b'/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj'
    )
    objects.append(b'4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj')
    objects.append(
        f'5 0 obj << /Length {len(content_stream)} >> stream\n'.encode('ascii') +
        content_stream +
        b'\nendstream endobj'
    )

    pdf = bytearray(b'%PDF-1.4\n')
    offsets = [0]
    for obj in objects:
        offsets.append(len(pdf))
        pdf.extend(obj)
        pdf.extend(b'\n')

    xref_offset = len(pdf)
    pdf.extend(f'xref\n0 {len(offsets)}\n'.encode('ascii'))
    pdf.extend(b'0000000000 65535 f \n')
    for offset in offsets[1:]:
        pdf.extend(f'{offset:010d} 00000 n \n'.encode('ascii'))

    pdf.extend(
        (
            f'trailer << /Size {len(offsets)} /Root 1 0 R >>\n'
            f'startxref\n{xref_offset}\n%%EOF'
        ).encode('ascii')
    )
    return bytes(pdf)


def build_booking_ticket_pdf(booking_type, booking, scan_url=None):
    booking_type = str(booking_type or '').strip().lower()
    lines = [
        f'Generated: {datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")}',
        f'Booking Reference: {getattr(booking, "booking_reference", "-")}',
        f'Ticket Type: {booking_type.upper() or "BOOKING"}',
        f'Payment Status: {str(getattr(booking, "payment_status", "") or "").upper() or "PENDING"}',
        f'Verified: {"YES" if bool(getattr(booking, "is_verified", False)) else "NO"}',
    ]

    verified_at = getattr(booking, 'verified_at', None)
    if verified_at:
        lines.append(f'Verified At: {verified_at.strftime("%b %d, %Y %I:%M %p")}')

    if booking_type == 'movie':
        showtime = booking.showtime
        lines.extend([
            f'Movie: {showtime.movie.title}',
            f'Cinema: {showtime.cinema.name}',
            f'Showtime: {showtime.show_date.strftime("%b %d, %Y")} {showtime.show_time.strftime("%I:%M %p")}',
            f'Tickets: {booking.num_tickets}',
            f'Seats: {booking.seat_numbers or "To be assigned"}',
        ])
    else:
        schedule = booking.schedule
        route = schedule.route
        lines.extend([
            f'Route: {route.origin} -> {route.destination}',
            f'Travel Date: {schedule.travel_date.strftime("%b %d, %Y")}',
            f'Departure: {route.departure_time.strftime("%I:%M %p")}',
            f'Passengers: {booking.num_tickets}',
            f'Seats: {booking.seat_numbers or "To be assigned"}',
        ])

    lines.append(f'Amount: PHP {float(getattr(booking, "total_amount", 0) or 0):.2f}')
    if scan_url:
        lines.append(f'Verification Link: {scan_url}')

    return build_simple_pdf('TicketHub Ticket', lines)
