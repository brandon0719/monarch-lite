import pytest

from app.services.merchant import clean


@pytest.mark.parametrize(
    "raw,payee,expected",
    [
        ("SQ *BLUE BOTTLE 0423", None, "Blue Bottle"),
        ("TST* SWEETGREEN 12345", None, "Sweetgreen"),
        ("PAYPAL *SPOTIFY", None, "Spotify"),
        ("PP*NINTENDO", None, "Nintendo"),
        ("SQ *SQ *DOUBLE PREFIX", None, "Double Prefix"),
        ("DEBIT CARD PURCHASE - TRADER JOE'S #552", None, "Trader Joe's"),
        ("POS DEBIT WHOLEFDS MKT 10234", None, "Wholefds Mkt"),
        ("CHECKCARD 0915 CHIPOTLE 1234 SPRINGFIELD IL", None, "Chipotle"),
        ("PURCHASE AUTHORIZED ON 09/15 SAFEWAY 1234", None, "Safeway"),
        ("ACH DEBIT PUGET SOUND ENERGY", None, "Puget Sound Energy"),
        ("STARBUCKS SPRINGFIELD IL", None, "Starbucks"),
        ("COSTCO WHSE #0123 ISSAQUAH WA", None, "Costco Whse"),
        ("TARGET        00012345", None, "Target"),
        ("TRADER JOE S #123 SPRINGFIELD IL", None, "Trader Joe S"),
        ("Zelle payment to JOHN 09/14", None, "Zelle Payment To John"),
        ("APPLE.COM/BILL XXXX1234", None, "Apple.com/bill"),
        ("CHASE CREDIT CRD AUTOPAY", None, "Chase Credit Crd Autopay"),
        ("Interest Payment", None, "Interest Payment"),
        ("AplPay LAWSON * JP", None, "Lawson"),
        ("AplPay BIC CAMERA SH* JP", None, "Bic Camera Sh"),
        ("AplPay TST* UTOPIA BWHITESTONE NY", None, "Utopia"),
        ("UEP*KUNG FU TEA", None, "Kung Fu Tea"),
        ("SP STUSSY.COM", None, "Stussy.com"),
        ("SNACK* TP TEA  FLUSHIN", None, "Snack* Tp Tea Flushin"),
        ("NETFLIX.COM", "Netflix", "Netflix"),
        ("SPOTIFY USA", "Spotify", "Spotify"),
        ("", None, ""),
    ],
)
def test_clean(raw, payee, expected):
    assert clean(raw, payee) == expected
