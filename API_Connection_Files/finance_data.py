import csv
import json
import logging
import requests
import yfinance as yf
from datetime import datetime
from pathlib import Path

DATA_ROOT = Path(__file__).parent.parent / "Data"
CSV_DIR   = DATA_ROOT / "CSV"
JSON_DIR  = DATA_ROOT / "JSON"

logging.getLogger("yfinance").setLevel(logging.CRITICAL)

# ── 1. FX RATES (yfinance — no key required) ──────────────────────────────────
# GBP pairs relevant to jet engine material imports
GBP_FX_PAIRS = {
    "GBP/USD": ("GBPUSD=X", "USD per £1", "Dollar-priced commodities (oil, metals)"),
    "GBP/EUR": ("GBPEUR=X", "EUR per £1", "European Airbus supply chain"),
    "GBP/AUD": ("GBPAUD=X", "AUD per £1", "Australian materials"),
    "GBP/CAD": ("GBPCAD=X", "CAD per £1", "Canadian materials"),
    "GBP/CNY": ("GBPCNY=X", "CNY per £1", "Chinese manufacturing inputs"),
    "GBP/JPY": ("GBPJPY=X", "JPY per £1", "Japanese precision components"),
}

def get_fx_rates() -> dict:
    rates = {}
    for pair, (ticker, unit, note) in GBP_FX_PAIRS.items():
        try:
            fast_info = yf.Ticker(ticker).fast_info
            rates[pair] = {
                "ticker": ticker,
                "rate": fast_info.last_price,
                "unit": unit,
                "note": note,
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as e:
            rates[pair] = {"ticker": ticker, "rate": None, "unit": unit, "note": note, "error": str(e)}
    return rates


# ── 2. MULTI-COUNTRY ECONOMIC INDICATORS (World Bank API — no key required) ────
# https://api.worldbank.org/v2/  —  data may lag 1-2 years (annual survey-based)
COUNTRIES = {
    "United Kingdom": "GB",
    "United States":  "US",
    "Australia":      "AU",
    "Canada":         "CA",
    "Japan":          "JP",
    "Germany":        "DE",
    "France":         "FR",
    "China":          "CN",
}

INDICATORS = {
    "CPI Inflation":         ("FP.CPI.TOTL.ZG", "% per annum",        "Consumer price inflation, annual %"),
    "GDP Growth":            ("NY.GDP.MKTP.KD.ZG", "% per annum",     "Real GDP growth rate"),
    "Unemployment Rate":     ("SL.UEM.TOTL.ZS", "% of labour force",  "ILO unemployment rate"),
    "Lending Rate":          ("FR.INR.LEND",    "% per annum",         "Commercial lending interest rate"),
    "Real Interest Rate":    ("FR.INR.RINR",    "% per annum",         "Real interest rate (inflation-adjusted)"),
    "Manufacturing (% GDP)": ("NV.IND.MANF.ZS", "% of GDP",           "Manufacturing value added as share of GDP"),
}

def get_country_indicators(country_code: str) -> dict:
    results = {}
    for name, (indicator, unit, note) in INDICATORS.items():
        url = (
            f"https://api.worldbank.org/v2/country/{country_code}"
            f"/indicator/{indicator}?format=json&mrv=1"
        )
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            entry = resp.json()[1][0]
            results[name] = {
                "value": entry["value"],
                "year": entry["date"],
                "unit": unit,
                "note": note,
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as e:
            results[name] = {"value": None, "unit": unit, "note": note, "error": str(e)}
    return results

def get_all_country_indicators() -> dict:
    return {country: get_country_indicators(code) for country, code in COUNTRIES.items()}


# ── 3. HISTORICAL DATA ────────────────────────────────────────────────────────
def _week_of_month(dt) -> str:
    first_day = dt.replace(day=1)
    return f"W{(dt.day + first_day.weekday() - 1) // 7 + 1}"


def get_fx_rates_historical(period: str = "5y") -> dict:
    """Weekly OHLC history for each GBP pair via yfinance."""
    historical = {}
    for pair, (ticker, unit, _) in GBP_FX_PAIRS.items():
        try:
            hist = yf.Ticker(ticker).history(period=period, interval="1wk")
            data = {}
            for ts, row in hist.iterrows():
                dt = ts.to_pydatetime()
                year, month, week = str(dt.year), dt.strftime("%b"), _week_of_month(dt)
                data.setdefault(year, {}).setdefault(month, {})[week] = {
                    "date":  dt.strftime("%Y-%m-%d"),
                    "open":  round(float(row["Open"]),  6),
                    "high":  round(float(row["High"]),  6),
                    "low":   round(float(row["Low"]),   6),
                    "close": round(float(row["Close"]), 6),
                }
            historical[pair] = {"ticker": ticker, "unit": unit, "interval": "weekly", "data": data}
        except Exception as e:
            historical[pair] = {"ticker": ticker, "unit": unit, "error": str(e)}
    return historical


def get_country_indicators_historical(country_code: str, years: int = 5) -> dict:
    """Annual World Bank indicators for the last N years."""
    results = {}
    for name, (indicator, unit, note) in INDICATORS.items():
        url = (
            f"https://api.worldbank.org/v2/country/{country_code}"
            f"/indicator/{indicator}?format=json&mrv={years}"
        )
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            entries = resp.json()[1]
            data = {
                e["date"]: {"value": e["value"], "unit": unit}
                for e in entries if e["value"] is not None
            }
            results[name] = {"indicator": indicator, "unit": unit, "note": note, "interval": "annual", "data": data}
        except Exception as e:
            results[name] = {"indicator": indicator, "unit": unit, "note": note, "error": str(e)}
    return results


def get_all_country_indicators_historical(years: int = 5) -> dict:
    return {country: get_country_indicators_historical(code, years) for country, code in COUNTRIES.items()}


def save_historical_to_json(historical: dict, path: Path = JSON_DIR / "finance_data_historical.json") -> None:
    with open(path, "w") as f:
        json.dump(historical, f, indent=2)


def save_historical_to_csv(historical: dict, path: Path = CSV_DIR / "finance_data_historical.csv") -> None:
    rows = []
    for key, entry in historical.get("fx_rates", {}).items():
        if "data" not in entry:
            continue
        for year, months in entry["data"].items():
            for month, weeks in months.items():
                for week, d in weeks.items():
                    rows.append({
                        "category": "FX Rate", "name": key, "ticker": entry["ticker"],
                        "unit": entry["unit"], "year": year, "month": month, "week": week,
                        "interval": "weekly", **d,
                    })
    for country, indicators in historical.get("country_indicators", {}).items():
        for indicator_name, entry in indicators.items():
            if "data" not in entry:
                continue
            for year, d in entry["data"].items():
                rows.append({
                    "category": "Economic", "name": indicator_name, "country": country,
                    "unit": entry["unit"], "year": year, "interval": "annual",
                    "value": d.get("value"),
                })
    if not rows:
        return
    fieldnames = sorted({k for row in rows for k in row})
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


# ── SAVE ───────────────────────────────────────────────────────────────────────
def save_to_json(data: dict, path: Path = JSON_DIR / "finance_data.json") -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def save_to_csv(data: dict, path: Path = CSV_DIR / "finance_data.csv") -> None:
    rows = []
    for category, values in data.items():
        if category == "fx_rates":
            for pair, d in values.items():
                rows.append({"category": "FX Rate", "country": "UK", "indicator": pair, **d})
        elif category == "country_indicators":
            for country, indicators in values.items():
                for indicator, d in indicators.items():
                    rows.append({"category": "Economic", "country": country, "indicator": indicator, **d})

    if not rows:
        return
    fieldnames = sorted({k for row in rows for k in row})
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


# ── MAIN ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"Global Macroeconomic Indicators  —  {ts}\n")

    fx = get_fx_rates()
    print("  FX Rates (GBP pairs)")
    for pair, d in fx.items():
        if d.get("rate") is not None:
            print(f"    {pair:<12}  {d['rate']:.4f}  [{d['unit']}]")
        else:
            print(f"    {pair:<12}  ERROR: {d.get('error')}")

    print()
    country_data = get_all_country_indicators()
    for country, indicators in country_data.items():
        print(f"  {country}")
        for name, d in indicators.items():
            if d.get("value") is not None:
                print(f"    {name:<24}  {d['value']:.2f}  [{d['unit']}]  ({d.get('year', '')})")
            else:
                print(f"    {name:<24}  ERROR: {d.get('error')}")
        print()

    all_data = {"fx_rates": fx, "country_indicators": country_data}
    save_to_json(all_data)
    save_to_csv(all_data)
    print(f"Saved to {CSV_DIR / 'finance_data.csv'} and {JSON_DIR / 'finance_data.json'}")
