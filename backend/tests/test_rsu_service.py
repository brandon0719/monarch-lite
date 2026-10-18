import datetime as dt

import pytest

from app.services import rsu

D = dt.date


def test_amazon_schedule_dates_and_shares():
    got = rsu.amazon_5_15_40_40(D(2025, 3, 20), 400)
    assert got == [(D(2026, 3, 15), 20), (D(2027, 3, 15), 60), (D(2027, 9, 15), 80),
                   (D(2028, 3, 15), 80), (D(2028, 9, 15), 80), (D(2029, 3, 15), 80)]
    assert sum(s for _, s in got) == 400


@pytest.mark.parametrize("start", [D(2025, 1, 1), D(2025, 1, 15), D(2025, 1, 31), D(2024, 2, 29)])
def test_amazon_vests_fall_on_the_15th_of_the_anniversary_month(start):
    dates = [d for d, _ in rsu.amazon_5_15_40_40(start, 400)]
    assert dates[0] == D(start.year + 1, start.month, 15) and dates[1] == D(start.year + 2, start.month, 15)
    assert all(d.day == 15 for d in dates) and dates == sorted(dates)


@pytest.mark.parametrize("total", [1, 7, 13, 101])
def test_awkward_totals_sum_exactly_and_drop_zero_vests(total):
    got = rsu.amazon_5_15_40_40(D(2025, 3, 20), total)
    assert sum(s for _, s in got) == total and all(s > 0 for _, s in got)


def test_single_share_drops_the_zero_vests_and_keeps_only_the_last():
    assert rsu.amazon_5_15_40_40(D(2025, 3, 20), 1) == [(D(2029, 3, 15), 1)]


def test_december_start_wraps_the_year():
    got = rsu.amazon_5_15_40_40(D(2025, 12, 5), 400)
    assert [d for d, _ in got] == [D(2026, 12, 15), D(2027, 12, 15), D(2028, 6, 15),
                                   D(2028, 12, 15), D(2029, 6, 15), D(2029, 12, 15)]
    assert sum(s for _, s in got) == 400


def test_semiannual_count_bounds():
    assert rsu.semiannual(D(2026, 5, 15), 7, 1) == [(D(2026, 5, 15), 7)]
    got = rsu.semiannual(D(2026, 5, 15), 20, 20)
    assert len(got) == 20 and all(s == 1 for _, s in got)
    assert got[0][0] == D(2026, 5, 15) and got[-1][0] == D(2035, 11, 15)  # 19 x 6 months = 114 months


def test_semiannual_clamps_month_end_and_puts_remainder_last():
    got = rsu.semiannual(D(2026, 8, 31), 10, 4)
    assert got == [(D(2026, 8, 31), 2), (D(2027, 2, 28), 2), (D(2027, 8, 31), 2), (D(2028, 2, 29), 4)]


def test_custom_validation():
    ok = [(D(2027, 1, 15), 5), (D(2026, 7, 15), 5)]
    assert rsu.check_custom(ok, 10) == sorted(ok)
    for bad in ([(D(2027, 1, 15), 5)], [(D(2027, 1, 15), 5), (D(2027, 1, 15), 5)], [(D(2027, 1, 15), 0), (D(2027, 2, 15), 10)], []):
        with pytest.raises(ValueError):
            rsu.check_custom(bad, 10)


def test_build_vests_dispatch_and_errors():
    assert rsu.build_vests("amazon_5_15_40_40", D(2025, 3, 20), 400)[0] == (D(2026, 3, 15), 20)
    assert len(rsu.build_vests("semiannual", D(2025, 3, 20), 8, first_vest=D(2026, 5, 15), count=4)) == 4
    with pytest.raises(ValueError):
        rsu.build_vests("semiannual", D(2025, 3, 20), 8)
    with pytest.raises(ValueError):
        rsu.build_vests("custom", D(2025, 3, 20), 8)
    with pytest.raises(ValueError):
        rsu.build_vests("semiannual", D(2025, 3, 20), 8, first_vest=D(2026, 5, 15), count=21)
