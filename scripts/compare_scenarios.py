"""Compare system cost, emissions and key capacities across scenarios.

Reads the summary workbooks written by solve_network.py for every scenario
that has results, and reports each scenario's cost relative to a reference
(uncontrolled charging by default). Two cost measures are given:

  objective   what the optimiser minimised (new investment plus operation)
  total cost  annualised cost of all assets including the existing fleet,
              from PyPSA's statistics (capex + opex)

    python scripts/compare_scenarios.py
    python scripts/compare_scenarios.py --reference SC_30
"""

import argparse
import logging

import pandas as pd

from _helpers import ROOT, load_config, paths, setup_logging

logger = logging.getLogger(__name__)


def scenario_table(config):
    """One row per solved year with cost, emissions and selected capacities."""
    rows = {}
    for year in config["years"]:
        workbook = paths(config)["summary"] / f"summary_{year}.xlsx"
        if not workbook.exists():
            continue
        headline = pd.read_excel(workbook, sheet_name="headline", index_col=0)["value"]
        capacity = pd.read_excel(workbook, sheet_name="capacity_by_carrier_MW", index_col=[0, 1])["capacity"]
        su = pd.read_excel(workbook, sheet_name="storage_units_p_nom_opt_MW", index_col=0)
        rows[year] = {
            "objective [MEUR]": headline["objective [MEUR]"],
            "total cost [MEUR]": headline["total cost [MEUR]"],
            "CO2 [Mt]": headline["CO2 emissions [Mt]"],
            "wind [GW]": capacity.get(("generators", "wind"), 0) / 1e3,
            "solar PV [GW]": sum(capacity.get(("generators", c), 0)
                                 for c in ("pv_rooftop", "pv_utility", "pv_agri")) / 1e3,
            "battery [GWh]": (su.p_nom_opt * su.max_hours).sum() / 1e3,
            "electrolyser [GW]": capacity.get(("links", "electrolyser"), 0) / 1e3,
        }
    return pd.DataFrame(rows).T


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--config")
    parser.add_argument("--reference", default="Dumb", help="scenario the others are compared with")
    args = parser.parse_args()

    setup_logging()
    names = list(load_config(args.config)["scenarios"])
    tables = {}
    for name in names:
        table = scenario_table(load_config(args.config, name))
        if table.empty:
            logger.info("%s: no results yet, skipped", name)
        else:
            tables[name] = table
    if not tables:
        raise SystemExit("No scenario has results. Run scripts/solve_network.py first.")

    result = pd.concat(tables, names=["scenario", "year"])
    if args.reference in tables:
        years = result.index.get_level_values("year")
        for column in ("objective [MEUR]", "total cost [MEUR]"):
            reference = tables[args.reference][column].reindex(years).values
            label = column.split(" [")[0]
            result[f"{label} vs {args.reference} [%]"] = (result[column].values / reference - 1) * 100

    folder = ROOT / "results" / "comparison"
    folder.mkdir(parents=True, exist_ok=True)
    result.round(3).to_csv(folder / "scenario_comparison.csv")
    with pd.option_context("display.width", 200, "display.max_columns", 20):
        print(result.round(2))
    logger.info("saved %s", (folder / "scenario_comparison.csv").relative_to(ROOT))


if __name__ == "__main__":
    main()
