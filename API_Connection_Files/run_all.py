import sys
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(ROOT))

from metal_data import (
    get_metal_prices, save_to_csv as metals_csv, save_to_json as metals_json,
    get_metal_prices_historical, save_historical_to_csv as metals_hist_csv,
    save_historical_to_json as metals_hist_json,
)
from energy_data import (
    get_energy_prices, save_to_csv as energy_csv, save_to_json as energy_json,
    get_energy_prices_historical, save_historical_to_csv as energy_hist_csv,
    save_historical_to_json as energy_hist_json,
)
from finance_data import (
    get_fx_rates, get_all_country_indicators,
    save_to_csv as finance_csv, save_to_json as finance_json,
    get_fx_rates_historical, get_all_country_indicators_historical,
    save_historical_to_csv as finance_hist_csv, save_historical_to_json as finance_hist_json,
)

if __name__ == "__main__":
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"Running all data fetches  —  {ts}\n")

    # ── Current snapshots ────────────────────────────────────────────────────
    print("── Metals (current) ────────────────────────────────")
    metals = get_metal_prices()
    metals_csv(metals)
    metals_json(metals)
    for metal, d in metals.items():
        if d.get("price") is not None:
            print(f"  {metal:<18}  ${d['price']:,.2f}  [{d['unit']}]")
        else:
            print(f"  {metal:<18}  ERROR: {d.get('error')}")

    print("\n── Energy (current) ────────────────────────────────")
    energy = get_energy_prices()
    energy_csv(energy)
    energy_json(energy)
    for region, commodities in energy.items():
        print(f"  {region}")
        for name, d in commodities.items():
            if d.get("price") is not None:
                print(f"    {name:<22}  ${d['price']:,.2f}  [{d['unit']}]")
            else:
                print(f"    {name:<22}  ERROR: {d.get('error')}")

    print("\n── Finance (current) ───────────────────────────────")
    fx = get_fx_rates()
    country_data = get_all_country_indicators()
    finance_csv({"fx_rates": fx, "country_indicators": country_data})
    finance_json({"fx_rates": fx, "country_indicators": country_data})
    for pair, d in fx.items():
        if d.get("rate") is not None:
            print(f"  {pair:<12}  {d['rate']:.4f}  [{d['unit']}]")
    for country, indicators in country_data.items():
        print(f"\n  {country}")
        for name, d in indicators.items():
            if d.get("value") is not None:
                print(f"    {name:<24}  {d['value']:.2f}  [{d['unit']}]  ({d.get('year', '')})")
            else:
                print(f"    {name:<24}  ERROR: {d.get('error')}")

    # ── Historical (5 years, weekly / annual) ────────────────────────────────
    print("\n\n── Historical data (5 years) ───────────────────────")

    print("  Fetching metals history...")
    metals_hist = get_metal_prices_historical()
    metals_hist_csv(metals_hist)
    metals_hist_json(metals_hist)
    for metal, entry in metals_hist.items():
        weeks = sum(len(w) for m in entry.get("data", {}).values() for w in m.values())
        print(f"  {metal:<18}  {weeks} weeks")

    print("  Fetching energy history...")
    energy_hist = get_energy_prices_historical()
    energy_hist_csv(energy_hist)
    energy_hist_json(energy_hist)
    for region, commodities in energy_hist.items():
        for name, entry in commodities.items():
            weeks = sum(len(w) for m in entry.get("data", {}).values() for w in m.values())
            print(f"  {region} / {name:<22}  {weeks} weeks")

    print("  Fetching FX & macro history...")
    fx_hist = get_fx_rates_historical()
    country_hist = get_all_country_indicators_historical()
    finance_hist_json({"fx_rates": fx_hist, "country_indicators": country_hist})
    finance_hist_csv({"fx_rates": fx_hist, "country_indicators": country_hist})
    for pair, entry in fx_hist.items():
        weeks = sum(len(w) for m in entry.get("data", {}).values() for w in m.values())
        print(f"  {pair:<12}  {weeks} weeks")

    print("\nAll data saved to Data/CSV/ and Data/JSON/")

    # ── Load into database ───────────────────────────────────────────────────
    print("\n── Loading into database ───────────────────────────")
    from Database.db_setup import build as db_build
    from Database.db_loader import load_all as db_load
    db_build()
    db_load()
