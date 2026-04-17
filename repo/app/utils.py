from datetime import datetime


def safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_date(value, fmt="%Y-%m-%d"):
    try:
        return datetime.strptime(value, fmt)
    except (TypeError, ValueError):
        return None
