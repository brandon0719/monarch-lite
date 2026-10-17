"""One-off: list what SimpleFIN returns for the owner's token. Run: python -m app.coverage_check"""
import datetime as dt

from .services.simplefin import fetch_accounts


def main() -> None:
    today = dt.date.today()
    payload = fetch_accounts(today - dt.timedelta(days=30), today + dt.timedelta(days=1))
    for error in payload.get("errors") or []:
        print("ERROR:", error)
    for acct in payload.get("accounts", []):
        org = (acct.get("org") or {}).get("name", "?")
        print(
            f"{org:<28} {acct.get('name', ''):<36} balance={acct.get('balance')} "
            f"txns={len(acct.get('transactions', []))} holdings={len(acct.get('holdings', []))}"
        )


if __name__ == "__main__":
    main()
