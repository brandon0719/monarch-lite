import datetime as dt

from app.services import recurring as r

D = dt.date


def monthly(merchant, cents, n, start=D(2026, 5, 10)):
    return [(merchant, r.step(start, "monthly", k), cents) for k in range(n)]


def test_step_monthly_clamps_to_month_end_and_recovers():
    a = D(2026, 1, 31)
    assert [r.step(a, "monthly", k) for k in range(4)] == [D(2026, 1, 31), D(2026, 2, 28), D(2026, 3, 31), D(2026, 4, 30)]


def test_step_weekly_year_wrap_and_yearly_feb29():
    assert r.step(D(2026, 10, 1), "weekly", 2) == D(2026, 10, 15)
    assert r.step(D(2026, 12, 15), "monthly", 1) == D(2027, 1, 15)
    assert r.step(D(2028, 2, 29), "yearly", 1) == D(2029, 2, 28)
    assert r.step(D(2028, 2, 29), "yearly", 4) == D(2032, 2, 29)


def test_amount_matches_ten_percent_same_sign():
    assert r.amount_matches(-1000, -1100) and r.amount_matches(-1000, -900)
    assert not r.amount_matches(-1000, -1101)
    assert not r.amount_matches(-1000, 1000)
    assert r.amount_matches(300000, 310000)


def test_next_due_follows_the_last_paid_date():
    anchor = D(2026, 8, 10)
    assert r.next_due(anchor, "monthly", []) == anchor
    assert r.next_due(anchor, "monthly", [D(2026, 8, 14), D(2026, 9, 6)]) == D(2026, 10, 10)
    assert r.next_due(anchor, "monthly", [D(2026, 7, 10)]) == anchor  # before the series window: ignored
    assert r.next_due(anchor, "monthly", [D(2026, 8, 5)]) == D(2026, 9, 10)  # window opens 5 days before
    assert r.next_due(anchor, "monthly", [D(2026, 8, 4)]) == anchor  # before s_0 - 5: ignored


def test_payment_seven_days_late_still_pays_its_date():
    anchor = D(2026, 6, 10)
    assert r.next_due(anchor, "monthly", [D(2026, 6, 17)]) == D(2026, 7, 10)
    assert r.next_due(anchor, "monthly", [D(2026, 6, 10), D(2026, 7, 17)]) == D(2026, 8, 10)


def test_rent_on_the_first_paid_on_the_ninth_is_never_stuck():
    anchor = D(2026, 8, 1)
    paid = [D(2026, 8, 9), D(2026, 9, 9), D(2026, 10, 9)]
    assert r.next_due(anchor, "monthly", paid) == D(2026, 11, 1)


def test_missed_old_cycle_does_not_pin_next_due():
    anchor = D(2026, 6, 10)
    paid = [D(2026, 6, 10), D(2026, 8, 10), D(2026, 9, 10), D(2026, 10, 10)]  # July never matched
    assert r.next_due(anchor, "monthly", paid) == D(2026, 11, 10)


def test_several_payments_in_one_window_pay_one_date():
    # Aug 4 and Aug 6 both fall in the window of Aug 8 (Aug 3 .. Aug 9); Aug 15 stays due.
    assert r.next_due(D(2026, 8, 1), "weekly", [D(2026, 8, 4), D(2026, 8, 6)]) == D(2026, 8, 15)
    assert r.next_due(D(2026, 8, 1), "weekly", [D(2026, 8, 4)]) == D(2026, 8, 15)


def test_upcoming_dates_late_item_once_then_future_dates():
    today = D(2026, 10, 17)
    got = r.upcoming_dates(D(2026, 9, 1), "weekly", D(2026, 10, 6), today, D(2026, 10, 31))
    assert got == [D(2026, 10, 6), D(2026, 10, 20), D(2026, 10, 27)]
    assert r.upcoming_dates(D(2026, 12, 1), "monthly", D(2026, 12, 1), today, D(2026, 11, 16)) == []


def test_detects_monthly_weekly_and_yearly():
    txns = (
        monthly("Spotify", -1899, 3)
        + [("Gym", D(2026, 9, 1) + dt.timedelta(days=7 * k), -2500) for k in range(4)]
        + [("Domain", D(2023 + k, 6, 1), -1500) for k in range(3)]
    )
    got = {s["merchant"]: s for s in r.detect(txns)}
    assert got["Spotify"] == {"merchant": "Spotify", "cadence": "monthly", "amount_cents": -1899, "count": 3,
                              "last_date": D(2026, 7, 10), "next_date": D(2026, 8, 10)}
    assert got["Gym"]["cadence"] == "weekly" and got["Gym"]["count"] == 4
    assert got["Domain"]["cadence"] == "yearly"
    assert [s["merchant"] for s in r.detect(txns)] == ["Gym", "Spotify", "Domain"]


def test_amount_outlier_irregular_gap_and_too_few_block_detection():
    outlier = monthly("A", -1000, 3)
    outlier[1] = ("A", outlier[1][1], -1200)
    irregular = [("B", D(2026, 5, 1), -500), ("B", D(2026, 5, 31), -500), ("B", D(2026, 7, 15), -500)]
    few = monthly("C", -700, 2)
    assert r.detect(outlier + irregular + few) == []


def test_signs_are_separate_groups_and_latest_amount_wins():
    txns = monthly("Bank", 400, 3) + [("Bank", D(2026, 5, 20), -9999)]
    (s,) = r.detect(txns)
    assert (s["merchant"], s["amount_cents"]) == ("Bank", 400)
    drift = monthly("Netflix", -1500, 2) + [("Netflix", D(2026, 7, 10), -1600)]
    assert r.detect(drift)[0]["amount_cents"] == -1600


def test_upcoming_dates_skip_paid_dates_after_a_missed_one():
    today = D(2026, 10, 17)
    anchor = D(2026, 6, 10)
    paid = [D(2026, 6, 10), D(2026, 8, 10), D(2026, 9, 10), D(2026, 10, 10)]
    due = r.next_due(anchor, "monthly", paid)
    assert r.upcoming_dates(anchor, "monthly", due, today, D(2026, 11, 16)) == [D(2026, 11, 10)]


def test_is_late_after_the_grace_period():
    due = D(2026, 10, 10)
    assert not r.is_late(due, D(2026, 10, 15))  # 5 days after: still grace
    assert r.is_late(due, D(2026, 10, 16))
    assert not r.is_late(due, D(2026, 10, 1))


def test_gap_edges_are_accepted_and_one_beyond_rejected():
    def run(gap, n=3):
        return r.detect([("M", D(2026, 1, 1) + dt.timedelta(days=gap * k), -1000) for k in range(n)])

    for cadence, ok, bad in (("weekly", (6, 8), (5, 9)), ("monthly", (27, 33), (26, 34)),
                             ("yearly", (358, 372), (357, 373))):
        for gap in ok:
            assert [s["cadence"] for s in run(gap)] == [cadence], (cadence, gap)
        for gap in bad:
            assert run(gap) == [], (cadence, gap)


def test_ten_percent_boundary():
    assert r.amount_matches(-1000, -1100) and r.amount_matches(-1000, -900)
    assert not r.amount_matches(-100000, -110010) and not r.amount_matches(-100000, -89990)  # 10.01%
    assert r.amount_matches(-100000, -110000)
    drift = [("Z", D(2026, 1, 1) + dt.timedelta(days=30 * k), c) for k, c in enumerate((-1000, -1000, -1100))]
    assert len(r.detect(drift)) == 1
    over = [("Z", D(2026, 1, 1) + dt.timedelta(days=30 * k), c) for k, c in enumerate((-100000, -100000, -110010))]
    assert r.detect(over) == []


def test_detect_sort_breaks_last_date_ties_by_merchant_descending():
    txns = monthly("Alpha", -1000, 3) + monthly("Beta", -2000, 3)
    assert [s["merchant"] for s in r.detect(txns)] == ["Beta", "Alpha"]
