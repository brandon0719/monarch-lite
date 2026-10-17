from decimal import ROUND_HALF_UP, Decimal, InvalidOperation


def to_cents(value: str | int | Decimal) -> int:
    """'-1,234.56' -> -123456. Decimal only, never float (NFR-DATA-03)."""
    text = str(value).replace(",", "").replace("$", "").strip()
    try:
        amount = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"not a money amount: {value!r}") from exc
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
