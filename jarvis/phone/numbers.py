"""Phone number normalization (defaults to Serbia, +381)."""

from __future__ import annotations

import re


def normalize_phone(raw: str, country_code: str = "381") -> str:
    """'064 123 4567' -> '+381641234567'. Returns '' for things that aren't numbers."""
    if not raw:
        return ""
    s = raw.strip()
    plus = s.startswith("+")
    digits = re.sub(r"\D", "", s)
    if len(digits) < 3:
        return ""
    if plus:
        return "+" + digits
    if digits.startswith("00"):
        return "+" + digits[2:]
    if digits.startswith("0"):
        return f"+{country_code}{digits[1:]}"
    if digits.startswith(country_code) and len(digits) > 9:
        return "+" + digits
    return digits  # short codes / service numbers stay as they are


def digits_only(phone: str) -> str:
    return re.sub(r"\D", "", phone)
