#!/usr/bin/env python3
"""Fetch Indian index price history from yfinance and write per-index JSON files.

Idempotent: loads existing JSON, fetches new rows, dedupes by date, sorts ascending, writes back.
First run backfills full history (>2015). One index failing does not abort the others.
Always updates meta.json with a heartbeat timestamp even if every source fails.
"""

import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
import yfinance as yf

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

INDICES = {
    "nifty50": {
        "ticker": "^NSEI",
        "name": "Nifty 50",
        "source": "yfinance",
    },
    "sensex": {
        "ticker": "^BSESN",
        "name": "Sensex",
        "source": "yfinance",
    },
    "nifty500": {
        "ticker": "^CRSLDX",
        "name": "Nifty 500",
        "source": "yfinance",
    },
    "nifty_midcap150": {
        "ticker": "NIFTYMIDCAP150.NS",
        "name": "Nifty Midcap 150",
        "source": "yfinance",
    },
    "nifty_next50": {
        "ticker": "JUNIORBEES.NS",
        "name": "Nifty Next 50 (Junior BeES ETF proxy)",
        "source": "yfinance",
    },
    "gold": {
        "ticker": "GOLDBEES.NS",
        "name": "Gold (Nippon Gold BeES ETF proxy)",
        "source": "yfinance",
    },
}


def load_existing(path: Path) -> list[dict]:
    if path.exists():
        with open(path, "r") as f:
            return json.load(f)
    return []


def validate_series(rows: list[dict], key: str) -> bool:
    """Check dates are monotonic and close values are in a plausible range."""
    if len(rows) < 2:
        return len(rows) == 1
    for i in range(1, len(rows)):
        if rows[i]["date"] <= rows[i - 1]["date"]:
            print(f"  [{key}] Non-monotonic dates at index {i}: {rows[i-1]['date']} >= {rows[i]['date']}")
            return False
        if rows[i]["close"] <= 0:
            print(f"  [{key}] Non-positive close at {rows[i]['date']}: {rows[i]['close']}")
            return False
    recent = rows[-1]["close"]
    if recent < 10 or recent > 500000:
        print(f"  [{key}] Implausible latest close: {recent}")
        return False
    return True


def fetch_index(key: str, cfg: dict) -> tuple[str, list[dict] | None, str | None]:
    """Fetch price data for one index. Returns (key, rows_or_None, error_or_None)."""
    ticker = cfg["ticker"]
    json_path = DATA_DIR / f"{key}.json"
    existing = load_existing(json_path)
    existing_dates = {r["date"] for r in existing}

    if existing:
        last_date = max(existing_dates)
        start = (datetime.strptime(last_date, "%Y-%m-%d") - timedelta(days=5)).strftime("%Y-%m-%d")
    else:
        start = "2005-01-01"

    print(f"  [{key}] Fetching {ticker} from {start} ...")
    df = yf.download(ticker, start=start, progress=False)

    if df.empty:
        return key, None, f"yfinance returned empty data for {ticker}"

    if hasattr(df.columns, "droplevel"):
        try:
            df.columns = df.columns.droplevel(1)
        except (IndexError, ValueError):
            pass

    new_rows = []
    for idx_date, row in df.iterrows():
        d = idx_date.strftime("%Y-%m-%d")
        close_val = float(row["Close"])
        if d not in existing_dates and close_val > 0:
            new_rows.append({"date": d, "close": round(close_val, 2)})

    merged = existing + new_rows
    merged.sort(key=lambda r: r["date"])

    # Dedupe by date (keep last)
    seen = {}
    for r in merged:
        seen[r["date"]] = r
    merged = sorted(seen.values(), key=lambda r: r["date"])

    if not validate_series(merged, key):
        return key, None, f"Validation failed for {key}"

    with open(json_path, "w") as f:
        json.dump(merged, f, separators=(",", ":"))

    print(f"  [{key}] OK: {len(merged)} total rows ({len(new_rows)} new), latest {merged[-1]['date']}")
    return key, merged, None


def update_meta(results: dict[str, dict]):
    """Write/update data/meta.json with index statuses and heartbeat timestamp."""
    meta_path = DATA_DIR / "meta.json"
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    indices_meta = {}
    for key, info in results.items():
        indices_meta[key] = {
            "status": info["status"],
            "source": info["source"],
            "latestDate": info.get("latestDate"),
            "latestClose": info.get("latestClose"),
        }

    meta = {
        "updated": now_utc,
        "updatedISO8601": now_utc,
        "indices": indices_meta,
    }

    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)

    print(f"\nmeta.json updated at {now_utc}")


def check_staleness(results: dict[str, dict]) -> list[str]:
    """Return list of warning messages for indices stale > 3 days."""
    warnings = []
    today = date.today()
    for key, info in results.items():
        if info["status"] != "ok":
            continue
        latest = datetime.strptime(info["latestDate"], "%Y-%m-%d").date()
        age = (today - latest).days
        if age > 3:
            warnings.append(f"{key}: last data {info['latestDate']} ({age} days old)")
    return warnings


def send_telegram_alert(message: str):
    """Send a Telegram alert if TELEGRAM_TOKEN and TELEGRAM_CHAT are set."""
    token = os.environ.get("TELEGRAM_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT")
    if not token or not chat_id:
        print("Telegram secrets not configured, skipping alert.")
        return

    import urllib.request
    import urllib.parse

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}).encode()
    try:
        req = urllib.request.Request(url, data=data)
        urllib.request.urlopen(req, timeout=10)
        print("Telegram alert sent.")
    except Exception as e:
        print(f"Telegram alert failed: {e}")


MFAPI_INDICES = {
    "nifty_smallcap250": {
        "mf_code": 147623,
        "name": "Nifty Smallcap 250 (Motilal Oswal Index Fund NAV proxy)",
        "source": "mfapi",
    },
}


def fetch_mfapi_index(key: str, cfg: dict) -> tuple[str, list[dict] | None, str | None]:
    """Fetch index fund NAV data from MFAPI as a proxy for the index."""
    mf_code = cfg["mf_code"]
    json_path = DATA_DIR / f"{key}.json"
    existing = load_existing(json_path)
    existing_dates = {r["date"] for r in existing}

    print(f"  [{key}] Fetching MF {mf_code} from MFAPI ...")
    r = requests.get(f"https://api.mfapi.in/mf/{mf_code}", timeout=30)
    if r.status_code != 200:
        return key, None, f"MFAPI returned status {r.status_code}"

    data = r.json().get("data", [])
    if not data:
        return key, None, "MFAPI returned no data"

    new_rows = []
    for item in data:
        try:
            dt = datetime.strptime(item["date"], "%d-%m-%Y").strftime("%Y-%m-%d")
            nav = float(item["nav"])
            if dt not in existing_dates and nav > 0:
                new_rows.append({"date": dt, "close": round(nav, 4)})
        except (ValueError, KeyError):
            pass

    merged = existing + new_rows
    seen = {}
    for row in merged:
        seen[row["date"]] = row
    merged = sorted(seen.values(), key=lambda r: r["date"])

    if not validate_series(merged, key):
        return key, None, f"Validation failed for {key}"

    with open(json_path, "w") as f:
        json.dump(merged, f, separators=(",", ":"))

    print(f"  [{key}] OK: {len(merged)} total rows ({len(new_rows)} new), latest {merged[-1]['date']}")
    return key, merged, None


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    results = {}
    errors = []

    for key, cfg in INDICES.items():
        try:
            k, rows, err = fetch_index(key, cfg)
            if err:
                print(f"  [{key}] FAILED: {err}")
                errors.append(f"{key}: {err}")
                results[key] = {"status": "stale", "source": cfg["source"], "latestDate": None, "latestClose": None}
                existing = load_existing(DATA_DIR / f"{key}.json")
                if existing:
                    results[key]["latestDate"] = existing[-1]["date"]
                    results[key]["latestClose"] = existing[-1]["close"]
                    results[key]["status"] = "ok"
            else:
                results[key] = {
                    "status": "ok",
                    "source": cfg["source"],
                    "latestDate": rows[-1]["date"],
                    "latestClose": rows[-1]["close"],
                }
        except Exception as e:
            print(f"  [{key}] EXCEPTION: {e}")
            errors.append(f"{key}: {e}")
            results[key] = {"status": "stale", "source": cfg["source"], "latestDate": None, "latestClose": None}
            existing = load_existing(DATA_DIR / f"{key}.json")
            if existing:
                results[key]["latestDate"] = existing[-1]["date"]
                results[key]["latestClose"] = existing[-1]["close"]
                results[key]["status"] = "ok"

    for key, cfg in MFAPI_INDICES.items():
        try:
            k, rows, err = fetch_mfapi_index(key, cfg)
            if err:
                print(f"  [{key}] FAILED: {err}")
                errors.append(f"{key}: {err}")
                results[key] = {"status": "stale", "source": cfg["source"], "latestDate": None, "latestClose": None}
                existing = load_existing(DATA_DIR / f"{key}.json")
                if existing:
                    results[key]["latestDate"] = existing[-1]["date"]
                    results[key]["latestClose"] = existing[-1]["close"]
                    results[key]["status"] = "ok"
            else:
                results[key] = {
                    "status": "ok",
                    "source": cfg["source"],
                    "latestDate": rows[-1]["date"],
                    "latestClose": rows[-1]["close"],
                }
        except Exception as e:
            print(f"  [{key}] EXCEPTION: {e}")
            errors.append(f"{key}: {e}")
            results[key] = {"status": "stale", "source": cfg["source"], "latestDate": None, "latestClose": None}
            existing = load_existing(DATA_DIR / f"{key}.json")
            if existing:
                results[key]["latestDate"] = existing[-1]["date"]
                results[key]["latestClose"] = existing[-1]["close"]
                results[key]["status"] = "ok"

    update_meta(results)

    # Check staleness and alert
    stale_warnings = check_staleness(results)
    if stale_warnings:
        msg = "⚠️ *Zerodha XIRR Benchmark — Stale Index Data*\n\n" + "\n".join(stale_warnings)
        print(f"\nStale warnings:\n" + "\n".join(stale_warnings))
        send_telegram_alert(msg)

    if errors:
        print(f"\n{len(errors)} error(s) during fetch:")
        for e in errors:
            print(f"  - {e}")
        print("(Heartbeat commit will still proceed.)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
