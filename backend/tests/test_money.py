import pytest

from app.money import to_cents


@pytest.mark.parametrize(
    "raw,expected",
    [("-12.30", -1230), ("1,234.56", 123456), ("$5", 500), ("0.1", 10), (0, 0), ("-0.005", -1), (" 7.5 ", 750)],
)
def test_to_cents(raw, expected):
    assert to_cents(raw) == expected


def test_sums_are_exact():
    assert to_cents("0.1") + to_cents("0.2") == 30


def test_rejects_garbage():
    with pytest.raises(ValueError):
        to_cents("abc")
