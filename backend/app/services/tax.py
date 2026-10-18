"""Tax figures per year from YAML, and pure withholding math (M5 R2 spec). Integer cents; rates in % or bp."""
from dataclasses import dataclass
from pathlib import Path

import yaml

TAX_DIR = Path(__file__).resolve().parent.parent / "tax"
FILINGS = ("single", "married_jointly")
MAX_CENTS = 10**12


@dataclass(frozen=True)
class TaxYear:
    year: int
    standard_deduction: dict[str, int]
    brackets: dict[str, list[tuple[int, int]]]
    supplemental_pct: int
    supplemental_high_pct: int
    supplemental_high_threshold: int
    ss_bp: int
    ss_wage_base: int
    medicare_bp: int
    medicare_additional_bp: int
    medicare_threshold: int
    state_name: str
    state_payroll: list[tuple[str, int]]
    raw: dict


def _int(value, name: str, lo: int = 0, hi: int = MAX_CENTS) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise ValueError(f"{name} must be an integer from {lo} to {hi}")
    return value


def _name(value, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _brackets(rows, name: str) -> list[tuple[int, int]]:
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"{name} must be a non-empty list")
    if any(not isinstance(r, list) or len(r) != 2 for r in rows):
        raise ValueError(f"{name} rows must be [lower_cents, rate_pct]")
    out = [(_int(r[0], f"{name} lower"), _int(r[1], f"{name} rate", 0, 100)) for r in rows]
    if out[0][0] != 0 or any(b[0] <= a[0] for a, b in zip(out, out[1:])):
        raise ValueError(f"{name} must start at 0 and be strictly ascending")
    return out


def parse(data: dict) -> TaxYear:
    try:
        fed, fica, state = data["federal"], data["fica"], data["state"]
        payroll = []
        for item in state["payroll"]:
            if not isinstance(item.get("name"), str) or not item["name"].strip():
                raise ValueError("state payroll items need a name")
            payroll.append((item["name"].strip(), _int(item["rate_bp"], "state rate_bp", 0, 10000)))
        return TaxYear(
            year=_int(data["year"], "year", 2000, 2100),
            standard_deduction={f: _int(fed["standard_deduction"][f], f"standard_deduction.{f}") for f in FILINGS},
            brackets={f: _brackets(fed["brackets"][f], f"brackets.{f}") for f in FILINGS},
            supplemental_pct=_int(fed["supplemental"]["rate_pct"], "supplemental.rate_pct", 0, 100),
            supplemental_high_pct=_int(fed["supplemental"]["high_rate_pct"], "supplemental.high_rate_pct", 0, 100),
            supplemental_high_threshold=_int(fed["supplemental"]["high_threshold"], "supplemental.high_threshold"),
            ss_bp=_int(fica["social_security"]["rate_bp"], "social_security.rate_bp", 0, 10000),
            ss_wage_base=_int(fica["social_security"]["wage_base"], "social_security.wage_base"),
            medicare_bp=_int(fica["medicare"]["rate_bp"], "medicare.rate_bp", 0, 10000),
            medicare_additional_bp=_int(fica["medicare"]["additional_bp"], "medicare.additional_bp", 0, 10000),
            medicare_threshold=_int(fica["medicare"]["additional_threshold"], "medicare.additional_threshold"),
            state_name=_name(state["name"], "state name"),
            state_payroll=payroll,
            raw=data,
        )
    except (KeyError, TypeError, IndexError, AttributeError) as exc:
        raise ValueError(f"Invalid tax config: {exc!r}") from exc


def years_before(year: int) -> list[int]:
    """Years below `year` that have a config file, newest first."""
    found = [int(p.stem) for p in TAX_DIR.glob("*.yaml") if p.stem.isdigit()]
    return sorted((y for y in found if y < year), reverse=True)


def load_year(year: int, tax_dir: Path | None = None) -> TaxYear | None:
    path = (tax_dir or TAX_DIR) / f"{year}.yaml"
    if not path.is_file():
        return None
    try:
        data = yaml.safe_load(path.read_text())
    except (yaml.YAMLError, RecursionError) as exc:
        raise ValueError(f"{path.name} is not valid YAML: {type(exc).__name__}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} must be a mapping")
    return parse(data)


def half_up_div(n: int, d: int) -> int:
    """n / d rounded half up, for n >= 0 and d > 0."""
    return (2 * n + d) // (2 * d)


def pct_of(cents: int, bp: int) -> int:
    return half_up_div(cents * bp, 10000)


def bracket_tax(taxable: int, brackets: list[tuple[int, int]]) -> int:
    total = 0
    for i, (lower, rate) in enumerate(brackets):
        if taxable <= lower:
            break
        upper = brackets[i + 1][0] if i + 1 < len(brackets) else taxable
        total += (min(taxable, upper) - lower) * rate
    return half_up_div(total, 100)


def federal_regular(taxable_period: int, periods: int, filing: str, ty: TaxYear, extra: int = 0) -> int:
    """Annualize, subtract the standard deduction, apply brackets, de-annualize; plus any extra withholding."""
    annual = max(0, taxable_period * periods - ty.standard_deduction[filing])
    return half_up_div(bracket_tax(annual, ty.brackets[filing]), periods) + extra


def federal_supplemental(amount: int, ytd_supp_before: int, ty: TaxYear) -> int:
    t = ty.supplemental_high_threshold
    high = max(0, ytd_supp_before + amount - t) - max(0, ytd_supp_before - t)
    return half_up_div((amount - high) * ty.supplemental_pct + high * ty.supplemental_high_pct, 100)


def social_security(gross: int, ytd_before: int, ty: TaxYear) -> int:
    return pct_of(min(gross, max(0, ty.ss_wage_base - ytd_before)), ty.ss_bp)


def medicare(gross: int, ytd_before: int, ty: TaxYear) -> int:
    t = ty.medicare_threshold
    over = max(0, ytd_before + gross - t) - max(0, ytd_before - t)
    return pct_of(gross, ty.medicare_bp) + pct_of(over, ty.medicare_additional_bp)
