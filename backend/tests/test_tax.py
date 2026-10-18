import copy

import pytest

from app.services import tax

CFG = {
    "year": 2026,
    "federal": {
        "standard_deduction": {"single": 1610000, "married_jointly": 3220000},
        "brackets": {
            "single": [[0, 10], [1240000, 12], [5040000, 22], [10570000, 24], [20177500, 32], [25622500, 35], [64060000, 37]],
            "married_jointly": [[0, 10], [2480000, 12], [10080000, 22], [21140000, 24], [40355000, 32], [51245000, 35], [76870000, 37]],
        },
        "supplemental": {"rate_pct": 22, "high_rate_pct": 37, "high_threshold": 100000000},
    },
    "fica": {"social_security": {"rate_bp": 620, "wage_base": 18450000},
             "medicare": {"rate_bp": 145, "additional_bp": 90, "additional_threshold": 20000000}},
    "state": {"name": "WA", "payroll": [{"name": "WA Cares", "rate_bp": 58}, {"name": "PFML", "rate_bp": 0}]},
}
TY = tax.parse(CFG)


def test_committed_2026_yaml_loads():
    ty = tax.load_year(2026)
    assert ty is not None and ty.year == 2026 and ty.brackets["single"][0] == (0, 10)
    assert tax.load_year(1999) is None


def test_bracket_tax_and_regular_federal():
    assert tax.bracket_tax(9190000, TY.brackets["single"]) == 1493000          # $14,930 on $91,900
    assert tax.bracket_tax(0, TY.brackets["single"]) == 0
    # $10,000 monthly gross, $1,000 401(k): annual taxable 108,000 - 16,100 = 91,900 -> 14,930 / 12
    assert tax.federal_regular(900000, 12, "single", TY) == 124417
    assert tax.federal_regular(900000, 12, "single", TY, extra=5000) == 129417
    assert tax.federal_regular(100000, 12, "single", TY) == 0                  # under the standard deduction
    assert tax.federal_regular(900000, 12, "married_jointly", TY) < 124417


def test_supplemental_flat_and_high_rate_split():
    assert tax.federal_supplemental(5000000, 0, TY) == 1100000                  # 22%
    assert tax.federal_supplemental(2000000, 99000000, TY) == 220000 + 370000   # 1M at 22%, 1M at 37%


def test_social_security_wage_base_and_additional_medicare():
    assert tax.social_security(100000, 18400000, TY) == 3100                   # only $500 left under the base
    assert tax.social_security(100000, 18450000, TY) == 0
    assert tax.medicare(100000, 19950000, TY) == 1450 + 450                    # $500 over the $200k threshold
    assert tax.medicare(1000000, 0, TY) == 14500


@pytest.mark.parametrize("mutate", [
    lambda c: c["federal"]["brackets"]["single"].__setitem__(0, [100, 10]),       # first lower bound not 0
    lambda c: c["federal"]["brackets"]["single"].__setitem__(2, [1000, 22]),      # not ascending
    lambda c: c["fica"]["social_security"].pop("wage_base"),
    lambda c: c["fica"]["medicare"].__setitem__("rate_bp", -1),
    lambda c: c["federal"]["standard_deduction"].__setitem__("single", True),
    lambda c: c["state"]["payroll"].append({"name": "", "rate_bp": 1}),
])
def test_parse_rejects_bad_config(mutate):
    bad = copy.deepcopy(CFG)
    mutate(bad)
    with pytest.raises(ValueError):
        tax.parse(bad)


@pytest.mark.parametrize("text", ["federal: [unclosed", "a: !!python/object/apply:os.system ['true']", "- just\n- a list\n", ""])
def test_load_year_turns_any_bad_yaml_into_value_error(tmp_path, text):
    (tmp_path / "2030.yaml").write_text(text)
    with pytest.raises(ValueError):
        tax.load_year(2030, tmp_path)


@pytest.mark.parametrize("mutate", [
    lambda c: c["federal"]["brackets"]["single"].__setitem__(1, [1240000, 12, 99]),   # extra column
    lambda c: c["state"].__setitem__("name", None),
    lambda c: c["state"].__setitem__("name", {"x": 1}),
])
def test_parse_rejects_bad_row_shape_and_state_name(mutate):
    bad = copy.deepcopy(CFG)
    mutate(bad)
    with pytest.raises(ValueError):
        tax.parse(bad)


def test_exact_values_and_edges():
    assert tax.federal_regular(900000, 12, "married_jointly", TY) == 71667
    assert tax.half_up_div(5, 10) == 1 and tax.half_up_div(4, 10) == 0 and tax.half_up_div(15, 10) == 2
    assert tax.federal_supplemental(1000000, 150000000, TY) == 370000            # YTD already over $1M: all 37%
    assert tax.medicare(100000, 25000000, TY) == 1450 + 900                       # YTD already over threshold
