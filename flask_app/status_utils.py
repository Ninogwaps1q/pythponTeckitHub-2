"""Status display helpers kept outside app.py for easier reuse and testing."""

PAYMENT_STATUS_META = {
    'pending': ('Pending', 'warning'),
    'paid': ('Paid', 'success'),
    'completed': ('Paid', 'success'),
    'failed': ('Failed', 'danger'),
    'cancelled': ('Cancelled', 'secondary'),
    'refunded': ('Refunded', 'info'),
    'refund_pending': ('Refund Pending', 'warning'),
}


def normalize_payment_status(value):
    status = str(value or '').strip().lower()
    if not status:
        return 'pending'
    if status in ('succeeded', 'captured'):
        return 'paid'
    return status


def payment_status_label(value):
    status = normalize_payment_status(value)
    return PAYMENT_STATUS_META.get(status, (status.replace('_', ' ').title(), 'secondary'))[0]


def payment_status_badge_class(value):
    status = normalize_payment_status(value)
    return PAYMENT_STATUS_META.get(status, ('Unknown', 'secondary'))[1]


def payment_status_is_final(value):
    return normalize_payment_status(value) in ('paid', 'completed', 'failed', 'cancelled', 'refunded')


def verification_label(is_verified):
    return 'Verified' if bool(is_verified) else 'Not Verified'
