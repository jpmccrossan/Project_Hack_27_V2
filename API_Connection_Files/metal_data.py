import csv
import json
import yfinance as yf
from datetime import datetime
from pathlib import Path

DATA_ROOT = Path(__file__).parent.parent / "Data"
CSV_DIR   = DATA_ROOT / "CSV"
JSON_DIR  = DATA_ROOT / "JSON"

# Metals used in jet engine construction that have Yahoo Finance futures tickers.
# Titanium, cobalt, and nickel are excluded — no reliable Yahoo Finance tickers.
# unit = the pricing unit for one contract price as quoted by Yahoo Finance.
JET_ENGINE_METALS = {
    "Aluminum":    ("ALI=F", "USD per lb"),        # fan cases, compressor housings
    "Steel (HRC)": ("HRC=F", "USD per short ton"), # shafts, structural components
    "Copper":      ("HG=F",  "USD per lb"),         # electrical wiring, heat exchangers
    "Platinum":    ("PL=F",  "USD per troy oz"),    # sensors, ignition systems
    "Palladium":   ("PA=F",  "USD per troy oz"),    # catalytic / sensor components
    "Gold":        ("GC=F",  "USD per troy oz"),    # corrosion-resistant coatings / connectors
    "Silver":      ("SI=F",  "USD per troy oz"),    # brazing alloys, electrical contacts
}


def get_metal_prices() -> dict:
    """Fetch current spot/futures prices for jet engine metals from Yahoo Finance."""
    prices = {}
    for metal, (ticker, unit) in JET_ENGINE_METALS.items():
        try:
            fast_info = yf.Ticker(ticker).fast_info
            prices[metal] = {
                "ticker": ticker,
                "price": fast_info.last_price,
                "unit": unit,
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as e:
            prices[metal] = {"ticker": ticker, "price": None, "unit": unit, "error": str(e)}
    return prices


def _week_of_month(dt) -> str:
    first_day = dt.replace(day=1)
    return f"W{(dt.day + first_day.weekday() - 1) // 7 + 1}"


def get_metal_prices_historical(period: str = "5y") -> dict:
    historical = {}
    for metal, (ticker, unit) in JET_ENGINE_METALS.items():
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
            historical[metal] = {"ticker": ticker, "unit": unit, "interval": "weekly", "data": data}
        except Exception as e:
            historical[metal] = {"ticker": ticker, "unit": unit, "error": str(e)}
    return historical


def save_historical_to_json(historical: dict, path: Path = JSON_DIR / "metal_prices_historical.json") -> None:
    with open(path, "w") as f:
        json.dump(historical, f, indent=2)


def save_historical_to_csv(historical: dict, path: Path = CSV_DIR / "metal_prices_historical.csv") -> None:
    rows = []
    for metal, entry in historical.items():
        if "data" not in entry:
            continue
        for year, months in entry["data"].items():
            for month, weeks in months.items():
                for week, d in weeks.items():
                    rows.append({
                        "metal": metal, "ticker": entry["ticker"], "unit": entry["unit"],
                        "year": year, "month": month, "week": week, **d,
                    })
    if not rows:
        return
    fieldnames = ["metal", "ticker", "unit", "year", "month", "week", "date", "open", "high", "low", "close"]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def save_to_csv(prices: dict, path: Path = CSV_DIR / "metal_prices.csv") -> None:
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["metal", "ticker", "price", "unit", "timestamp", "error"])
        writer.writeheader()
        for metal, data in prices.items():
            writer.writerow({"metal": metal, **data})


def save_to_json(prices: dict, path: Path = JSON_DIR / "metal_prices.json") -> None:
    with open(path, "w") as f:
        json.dump(prices, f, indent=2)


if __name__ == "__main__":
    print(f"Jet Engine Metal Prices  —  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    prices = get_metal_prices()

    for metal, data in prices.items():
        if data["price"] is not None:
            print(f"  {metal:<18} ({data['ticker']})  ${data['price']:,.2f}  [{data['unit']}]")
        else:
            print(f"  {metal:<18} ({data['ticker']})  ERROR: {data.get('error')}")

    save_to_csv(prices)
    save_to_json(prices)
    print(f"\nSaved to {CSV_DIR / 'metal_prices.csv'} and {JSON_DIR / 'metal_prices.json'}")
