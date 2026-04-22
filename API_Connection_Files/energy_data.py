import csv
import json
import logging
import yfinance as yf
from datetime import datetime
from pathlib import Path

DATA_ROOT = Path(__file__).parent.parent / "Data"
CSV_DIR   = DATA_ROOT / "CSV"
JSON_DIR  = DATA_ROOT / "JSON"

# Suppress noisy yfinance period-fallback warnings
logging.getLogger("yfinance").setLevel(logging.CRITICAL)

# Yahoo Finance does not carry retail electricity spot prices (£/kWh, $/kWh).
# The tickers below are commodity futures that underpin regional energy pricing.
# Each entry: (ticker, unit, note)
ENERGY_BY_REGION = {
    "USA": {
        "WTI Crude Oil":    ("CL=F", "USD per barrel", "US oil benchmark"),
        "Natural Gas":      ("NG=F", "USD per MMBtu",  "Henry Hub benchmark"),
        "Gasoline (RBOB)":  ("RB=F", "USD per gallon", "US retail fuel benchmark"),
        "Heating Oil":      ("HO=F", "USD per gallon", "US heating / diesel benchmark"),
    },
    "UK / Europe": {
        "Brent Crude Oil":  ("BZ=F",  "USD per barrel", "North Sea / European oil benchmark"),
        "Coal (Rotterdam)": ("MTF=F", "USD per tonne",  "European coal benchmark"),
    },
    "Australia": {
        "Coal (Rotterdam)": ("MTF=F", "USD per tonne",  "Closest available proxy — Newcastle Coal not on Yahoo Finance"),
    },
}


def get_energy_prices() -> dict:
    """Fetch current energy commodity futures prices from Yahoo Finance, grouped by region."""
    results = {}
    for region, commodities in ENERGY_BY_REGION.items():
        results[region] = {}
        for name, (ticker, unit, note) in commodities.items():
            try:
                fast_info = yf.Ticker(ticker).fast_info
                results[region][name] = {
                    "ticker": ticker,
                    "price": fast_info.last_price,
                    "unit": unit,
                    "note": note,
                    "timestamp": datetime.now().isoformat(),
                }
            except Exception as e:
                results[region][name] = {
                    "ticker": ticker,
                    "price": None,
                    "unit": unit,
                    "note": note,
                    "error": str(e),
                }
    return results


def _week_of_month(dt) -> str:
    first_day = dt.replace(day=1)
    return f"W{(dt.day + first_day.weekday() - 1) // 7 + 1}"


def get_energy_prices_historical(period: str = "5y") -> dict:
    historical = {}
    for region, commodities in ENERGY_BY_REGION.items():
        historical[region] = {}
        for name, (ticker, unit, note) in commodities.items():
            try:
                hist = yf.Ticker(ticker).history(period=period, interval="1wk")
                data = {}
                for ts, row in hist.iterrows():
                    dt = ts.to_pydatetime()
                    year, month, week = str(dt.year), dt.strftime("%b"), _week_of_month(dt)
                    data.setdefault(year, {}).setdefault(month, {})[week] = {
                        "date":  dt.strftime("%Y-%m-%d"),
                        "open":  round(float(row["Open"]),  4),
                        "high":  round(float(row["High"]),  4),
                        "low":   round(float(row["Low"]),   4),
                        "close": round(float(row["Close"]), 4),
                    }
                historical[region][name] = {"ticker": ticker, "unit": unit, "note": note, "interval": "weekly", "data": data}
            except Exception as e:
                historical[region][name] = {"ticker": ticker, "unit": unit, "note": note, "error": str(e)}
    return historical


def save_historical_to_json(historical: dict, path: Path = JSON_DIR / "energy_prices_historical.json") -> None:
    with open(path, "w") as f:
        json.dump(historical, f, indent=2)


def save_historical_to_csv(historical: dict, path: Path = CSV_DIR / "energy_prices_historical.csv") -> None:
    rows = []
    for region, commodities in historical.items():
        for commodity, entry in commodities.items():
            if "data" not in entry:
                continue
            for year, months in entry["data"].items():
                for month, weeks in months.items():
                    for week, d in weeks.items():
                        rows.append({
                            "region": region, "commodity": commodity,
                            "ticker": entry["ticker"], "unit": entry["unit"],
                            "year": year, "month": month, "week": week, **d,
                        })
    if not rows:
        return
    fieldnames = ["region", "commodity", "ticker", "unit", "year", "month", "week", "date", "open", "high", "low", "close"]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def save_to_csv(results: dict, path: Path = CSV_DIR / "energy_prices.csv") -> None:
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["region", "commodity", "ticker", "price", "unit", "note", "timestamp", "error"]
        )
        writer.writeheader()
        for region, commodities in results.items():
            for commodity, data in commodities.items():
                writer.writerow({"region": region, "commodity": commodity, **data})


def save_to_json(results: dict, path: Path = JSON_DIR / "energy_prices.json") -> None:
    with open(path, "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    print(f"Energy Commodity Prices  —  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    results = get_energy_prices()

    for region, commodities in results.items():
        print(f"  {region}")
        for name, data in commodities.items():
            if data["price"] is not None:
                print(f"    {name:<22} ({data['ticker']})  ${data['price']:,.2f}  [{data['unit']}]")
            else:
                print(f"    {name:<22} ({data['ticker']})  ERROR: {data.get('error')}")
        print()

    save_to_csv(results)
    save_to_json(results)
    print(f"Saved to {CSV_DIR / 'energy_prices.csv'} and {JSON_DIR / 'energy_prices.json'}")
