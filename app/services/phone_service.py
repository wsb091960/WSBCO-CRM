import re


def normalize_us_phone(value: str) -> str:
    """Return a US/Canada phone number in E.164 format."""
    raw = (value or "").strip()
    if raw.startswith("+"):
        digits = re.sub(r"\D", "", raw)
        if 10 <= len(digits) <= 15:
            return f"+{digits}"
        raise ValueError("Phone number is not a valid E.164 number.")

    digits = re.sub(r"\D", "", raw)
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"

    raise ValueError(
        "Enter a 10-digit US phone number or a complete E.164 number."
    )
