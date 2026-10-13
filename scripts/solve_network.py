"""Build and solve PyPSA-Italy for every planning year of one or more scenarios.

Each year is an hourly (8760 h), seven-zone capacity-expansion problem read
from data/<folder>/input_<year>.xlsx. The workbook sheets follow PyPSA's own
CSV layout, so a sheet called ``generators`` becomes generators.csv and
``loads-p_set`` becomes loads-p_set.csv.

The scenario's ``ev_mode`` then sets the charging strategy (V2G, smart
charging only, or uncontrolled). With ``myopic: true`` the years are solved
in sequence and the optimal capacities of one year become the lower bounds
of the next.

    python scripts/solve_network.py
    python scripts/solve_network.py --scenario V2G_30 SC_30 Dumb
    python scripts/solve_network.py --years 2025 2030 --solver highs
"""

import argparse
import logging
import shutil

import pandas as pd
import pypsa

from _helpers import load_config, paths, setup_logging, zone_of

logger = logging.getLogger(__name__)

# Sheets that document the inputs and are not read by PyPSA.
DOCUMENTATION_SHEETS = {"Notes", "Techn + Costs", "Components"}

# Tables a workbook may contain. Time-series sheets must be named
# "<table>-<attribute>"; a typo there would make PyPSA silently ignore the
# profile, so we refuse to run instead.
PYPSA_TABLES = {
    "network", "snapshots", "global_constraints", "buses", "carriers", "loads",
    "generators", "links", "stores", "storage_units", "lines", "transformers",
}

# Size attribute of each expandable component type.
SIZE = {"generators": "p_nom", "links": "p_nom", "storage_units": "p_nom", "stores": "e_nom"}


def workbook_to_csv(workbook, folder):
    """Write every model sheet of the workbook to <folder>/<sheet>.csv."""
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)

    xlsx = pd.ExcelFile(workbook)
    for sheet in xlsx.sheet_names:
        if sheet in DOCUMENTATION_SHEETS:
            continue
        table = sheet.split("-")[0]
        if table not in PYPSA_TABLES:
            raise ValueError(f"{workbook.name}: sheet '{sheet}' is not a PyPSA table name")
        xlsx.parse(sheet).to_csv(folder / f"{sheet}.csv", index=False)


def check_time_series(folder):
    """PyPSA assigns time series to snapshots by position, so lengths must match.

    Stray rows below hour 8760 (easy to leave behind when editing a workbook)
    would otherwise shift or break every profile.
    """
    def n_rows(csv):
        with open(csv, encoding="utf-8") as f:
            return sum(1 for _ in f) - 1

    expected = n_rows(folder / "snapshots.csv")
    for csv in folder.glob("*-*.csv"):
        if n_rows(csv) != expected:
            raise ValueError(f"{csv.name} has {n_rows(csv)} rows, snapshots.csv has {expected}")


def apply_ev_mode(n, mode):
    """Adapt the EV fleet in the workbook to the scenario's charging strategy.

    The workbooks describe the V2G case: on every zone's EV bus there is the
    flexible EV demand, the connected battery capacity (EV_store) and two
    links to the grid, smart_charging and V2G.
    """
    if mode not in ("v2g", "smart", "dumb"):
        raise ValueError(f"ev_mode must be 'v2g', 'smart' or 'dumb', not '{mode}'")
    if mode == "v2g":
        return

    n.remove("Link", n.links.index[n.links.carrier == "V2G"])
    if mode == "smart":
        return

    # Uncontrolled charging: the flexible share is added to the uncontrolled EV
    # load of the same zone (both use the same hourly charging profile), so the
    # total EV demand is identical across the three strategies.
    flexible = n.loads[n.loads.carrier == "EV"]
    uncontrolled = {zone_of(bus): name for name, bus in n.loads.bus[n.loads.carrier == "EV_dumb"].items()}
    p_set = n.loads_t.p_set
    for name, bus in flexible.bus.items():
        target = uncontrolled[zone_of(bus)]
        p_set[target] = p_set[target] + p_set[name]

    n.remove("Load", flexible.index)
    n.remove("Link", n.links.index[n.links.carrier == "smart_charging"])
    n.remove("Store", n.stores.index[n.stores.carrier == "EV_store"])


def set_extendable(n, extendable):
    for component, carriers in extendable.items():
        df = getattr(n, component)
        attr = f"{SIZE[component]}_extendable"
        df.loc[df.carrier.isin(carriers), attr] = True


def raise_lower_bounds(n, previous):
    """Use last year's optimal capacities as this year's minimum capacities.

    A bound already in the workbook is never lowered, and the new bound is
    capped at the technical maximum so the problem stays feasible.
    """
    for component, optimum in previous.items():
        df = getattr(n, component)
        size = SIZE[component]
        common = df.index.intersection(optimum.index)
        new_min = optimum[common].clip(upper=df.loc[common, f"{size}_max"])
        df.loc[common, f"{size}_min"] = pd.concat(
            [df.loc[common, f"{size}_min"], new_min], axis=1
        ).max(axis=1)


def optimal_sizes(n):
    return {c: getattr(n, c)[f"{SIZE[c]}_opt"].copy() for c in SIZE}


def previous_year_sizes(year, config, out):
    """When a myopic run starts mid-pathway, pick up the year before from disk."""
    earlier = [y for y in config["years"] if y < year]
    if not earlier:
        return None
    folder = out["networks"] / str(earlier[-1])
    if not folder.is_dir():
        logger.warning(
            "%s: no solved %s network found, so no capacities are carried forward",
            year, earlier[-1],
        )
        return None
    n = pypsa.Network()
    n.import_from_csv_folder(folder)
    logger.info("%s: carrying forward capacities from %s", year, earlier[-1])
    return optimal_sizes(n)


def ev_summary(n):
    p_set = n.loads_t.p_set
    energy = {
        carrier: p_set.reindex(columns=n.loads.index[n.loads.carrier == carrier], fill_value=0).sum().sum()
        for carrier in ("EV_dumb", "EV")
    }
    total = sum(energy.values())
    if total == 0:
        return "no EV demand"
    return f"EV demand {total / 1e6:.1f} TWh, {energy['EV'] / total:.0%} flexible"


def total_cost(n):
    """Annualised investment plus operating cost of all assets, MEUR."""
    return (n.statistics.capex().sum() + n.statistics.opex().sum()) / 1e6


def summarise(n):
    """Key results of one solved year, one DataFrame per Excel sheet."""
    weights = n.snapshot_weightings.generators
    gen = n.generators

    intensity = gen.carrier.map(n.carriers.co2_emissions).fillna(0.0)
    fuel_use = n.generators_t.p.div(gen.efficiency.fillna(1.0), axis=1)
    emissions_t = (weights @ fuel_use.mul(intensity, axis=1)).sum()

    capex = n.statistics.capex()
    opex = n.statistics.opex()

    return {
        "statistics": n.statistics(),
        "headline": pd.Series({
            "total cost [MEUR]": total_cost(n),
            "objective [MEUR]": n.objective / 1e6,
            "capex [MEUR]": capex.sum() / 1e6,
            "opex [MEUR]": opex.sum() / 1e6,
            "CO2 emissions [Mt]": emissions_t / 1e6,
        }).to_frame("value"),
        "cost_by_carrier_MEUR": capex.add(opex, fill_value=0).div(1e6).to_frame("total"),
        "capex_by_carrier_MEUR": capex.div(1e6).to_frame("capex"),
        "added_capacity_MW": (
            n.statistics.optimal_capacity() - n.statistics.installed_capacity()
        ).to_frame("added"),
        "energy_by_generator_MWh": (weights @ n.generators_t.p).to_frame("energy"),
        "dispatch_by_generator_MW": n.generators_t.p,
        "generators_p_nom_opt_MW": gen[["bus", "carrier", "p_nom_opt"]],
        "links_p_nom_opt_MW": n.links[["bus0", "bus1", "carrier", "p_nom_opt"]],
        "storage_units_p_nom_opt_MW": n.storage_units[["bus", "carrier", "p_nom_opt", "max_hours"]],
        "stores_e_nom_opt_MWh": n.stores[["bus", "carrier", "e_nom_opt"]],
        "capacity_by_carrier_MW": pd.concat({
            "generators": gen.p_nom_opt.groupby(gen.carrier).sum(),
            "links": n.links.p_nom_opt.groupby(n.links.carrier).sum(),
            "storage_units": n.storage_units.p_nom_opt.groupby(n.storage_units.carrier).sum(),
            "stores [MWh]": n.stores.e_nom_opt.groupby(n.stores.carrier).sum(),
        }).to_frame("capacity"),
    }


def export(n, year, out, full_excel):
    folder = out["networks"] / str(year)
    folder.mkdir(parents=True, exist_ok=True)
    n.export_to_csv_folder(folder, export_standard_types=False)

    out["summary"].mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(out["summary"] / f"summary_{year}.xlsx") as writer:
        for sheet, df in summarise(n).items():
            df.to_excel(writer, sheet_name=sheet[:31])

    if full_excel:
        with pd.ExcelWriter(out["summary"] / f"network_{year}.xlsx", engine="xlsxwriter") as writer:
            for csv in sorted(folder.glob("*.csv")):
                pd.read_csv(csv).to_excel(writer, sheet_name=csv.stem[:31], index=False)


def solve_year(year, config, out, previous=None):
    workbook = out["data"] / f"input_{year}.xlsx"
    csv_folder = out["input_csv"] / str(year)
    workbook_to_csv(workbook, csv_folder)

    check_time_series(csv_folder)

    n = pypsa.Network()
    n.import_from_csv_folder(csv_folder)
    apply_ev_mode(n, config["case"]["ev_mode"])
    logger.info("%s %s: %d snapshots, %s", config["scenario"], year, len(n.snapshots), ev_summary(n))

    set_extendable(n, config["extendable"])
    if previous:
        raise_lower_bounds(n, previous)

    solver = config["solver"]
    status, condition = n.optimize(solver_name=solver["name"], **(solver.get("options") or {}))
    if status != "ok":
        raise RuntimeError(f"{year}: solver returned {status} / {condition}")
    logger.info("%s %s: solved, objective %.1f MEUR, total cost incl. existing assets %.1f MEUR",
                config["scenario"], year, n.objective / 1e6, total_cost(n))

    export(n, year, out, config["export"]["full_excel"])
    return n


def solve_scenario(config, years):
    out = paths(config)
    previous = previous_year_sizes(years[0], config, out) if config["myopic"] else None
    for year in years:
        n = solve_year(year, config, out, previous)
        previous = optimal_sizes(n) if config["myopic"] else None
    logger.info("%s done, results in %s", config["scenario"], out["networks"].parent)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--config", help="config file (default: config/config.yaml)")
    parser.add_argument("--scenario", nargs="+", help="one or more scenarios from the config")
    parser.add_argument("--years", nargs="+", type=int, help="subset of years to solve")
    parser.add_argument("--solver", help="override the solver named in the config")
    args = parser.parse_args()

    setup_logging()
    for scenario in args.scenario or [None]:
        config = load_config(args.config, scenario)
        if args.solver:
            config["solver"] = {"name": args.solver, "options": {}}
        solve_scenario(config, sorted(args.years or config["years"]))


if __name__ == "__main__":
    main()
