"""Paths, configuration and plotting conventions shared by all scripts."""

import logging
from pathlib import Path

import pypsa
import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "config.yaml"

# Bidding zones used as model nodes (bus names start with these codes).
ZONES = {
    "R1": "North",
    "R2": "Centre-North",
    "R3": "Centre-South",
    "R4": "South",
    "R5": "Sardinia",
    "R6": "Sicily",
    "R7": "Calabria",
}

COLORS = {
    "coal": "#000000",
    "AC_import": "#A69885",
    "biomass": "#9EA950",
    "geothermal": "#6A5534",
    "reservoir_hydro": "#2A6D8C",
    "rh_hydro": "#6BAEE2",
    "wind": "#F36E21",
    "pv_rooftop": "#F5DA93",
    "pv_agri": "#EFC14B",
    "pv_utility": "#B39138",
    "natural_gas": "#666B6C",
    "phs_discharging": "#4C4F9E",
    "battery_discharging": "#BF88B3",
    "fuel_cell": "#1B9E61",
    "V2G": "#8DBF60",
    "shortage": "#6BC2C5",
    "phs_charging": "#9999CC",
    "battery_charging": "#953880",
    "electrolyser": "#127856",
    "smart_charging": "#008000",
    "battery": "#BF88B3",
    "EV_store": "#855BBD",
    "imports": "#916331",
    "exports": "#54573A",
}

LABELS = {
    "coal": "Coal power plant",
    "AC_import": "Import",
    "biomass": "Biomass power plant",
    "geothermal": "Geothermal power plant",
    "reservoir_hydro": "Hydro power plant",
    "rh_hydro": "Run-of-river hydro",
    "wind": "Onshore wind",
    "pv_rooftop": "Rooftop PV",
    "pv_agri": "Agrivoltaic",
    "pv_utility": "Utility-scale PV",
    "natural_gas": "Combined cycle gas turbine",
    "phs_discharging": "PHS discharging",
    "battery_discharging": "Battery discharging",
    "fuel_cell": "Fuel cell",
    "V2G": "V2G",
    "shortage": "Shortage",
    "phs_charging": "PHS charging",
    "battery_charging": "Battery charging",
    "electrolyser": "Electrolyser",
    "smart_charging": "Smart charging",
    "battery": "Battery",
    "EV_store": "EV battery store",
    "imports": "Imports from other zones",
    "exports": "Exports to other zones",
}

# Bottom-to-top order of the supply stack in all dispatch and energy plots.
SUPPLY_ORDER = [
    "coal", "AC_import", "biomass", "geothermal", "reservoir_hydro", "rh_hydro",
    "wind", "pv_rooftop", "pv_agri", "pv_utility", "natural_gas",
    "imports", "phs_discharging", "battery_discharging", "fuel_cell", "V2G", "shortage",
]

# Flexible consumption drawn above the demand line, bottom to top.
CHARGING_ORDER = ["phs_charging", "battery_charging", "electrolyser", "smart_charging", "exports"]


def setup_logging():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
    # linopy and pypsa are chatty at INFO level
    for name in ("linopy", "pypsa", "gurobipy", "highspy"):
        logging.getLogger(name).setLevel(logging.WARNING)


def load_config(path=None, scenario=None):
    """Read the config and select one scenario (default: ``scenario`` in the file)."""
    with open(path or DEFAULT_CONFIG, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    name = scenario or config["scenario"]
    if name not in config["scenarios"]:
        raise KeyError(f"Unknown scenario '{name}'. Defined: {', '.join(config['scenarios'])}")
    config["scenario"] = name
    config["case"] = config["scenarios"][name]
    return config


def add_common_args(parser):
    parser.add_argument("--config", help="config file (default: config/config.yaml)")
    parser.add_argument("--scenario", help="scenario defined in the config (default: the one set there)")
    return parser


def paths(config):
    """Input and output folders of the selected scenario."""
    results = ROOT / "results" / config["scenario"]
    return {
        "data": ROOT / "data" / config["case"]["data"],
        "input_csv": results / "input_csv",
        "networks": results / "networks",
        "summary": results / "summary",
        "plots": results / "plots",
    }


def solved_years(config):
    folder = paths(config)["networks"]
    years = [y for y in config["years"] if (folder / str(y)).is_dir()]
    if not years:
        raise FileNotFoundError(
            f"No solved networks in {folder}. Run scripts/solve_network.py first."
        )
    return years


def load_network(config, year):
    n = pypsa.Network()
    n.import_from_csv_folder(paths(config)["networks"] / str(year))
    return n


def zone_of(bus):
    """'R3_bus_el' -> 'R3'."""
    return bus.split("_")[0]


def sum_by(df, groups):
    """Sum the columns of a time-series frame by a grouping Series (e.g. carrier)."""
    return df.T.groupby(groups).sum().T


def supply_by_carrier(n, curtailed=True, buses=None):
    """Hourly generation per carrier in MW, optionally only at some buses.

    With ``curtailed=True`` variable renewables are shown at their available
    output (p_max_pu * p_nom_opt), so curtailed energy is part of the bar.
    This is how the paper presents the generation mix. With ``False`` every
    generator is shown at its actual dispatch.
    """
    gens = n.generators if buses is None else n.generators[n.generators.bus.isin(buses)]
    carrier = gens.carrier
    p = n.generators_t.p.reindex(columns=gens.index, fill_value=0.0)
    if curtailed:
        variable = n.generators_t.p_max_pu.columns.intersection(p.columns)
        p[variable] = n.generators_t.p_max_pu[variable] * n.generators.p_nom_opt[variable]
    return sum_by(p, carrier)


def link_flow(n, carrier, port="p0", buses=None):
    """Total power of all links of one carrier, MW, positive in the natural direction.

    port="p0": power withdrawn at bus0 (e.g. charging).
    port="p1": power delivered at bus1 (e.g. discharging), sign flipped to positive.
    ``buses`` limits the sum to links attached to those buses on that port.
    """
    links = n.links[n.links.carrier == carrier]
    if buses is not None:
        bus_col = "bus0" if port == "p0" else "bus1"
        links = links[links[bus_col].isin(buses)]
    flows = getattr(n.links_t, port).reindex(columns=links.index, fill_value=0.0)
    total = flows.sum(axis=1)
    return total if port == "p0" else -total


def storage_flows(n, buses=None):
    """Battery (storage unit) discharging and charging, MW."""
    su = n.storage_units
    if buses is not None:
        su = su[su.bus.isin(buses)]
    dispatch = n.storage_units_t.p_dispatch.reindex(columns=su.index, fill_value=0.0)
    store = n.storage_units_t.p_store.reindex(columns=su.index, fill_value=0.0)
    return dispatch.sum(axis=1), store.sum(axis=1)


def demand(n, buses=None):
    """Electricity demand in MW: (conventional load, conventional + uncontrolled EV load).

    Uncontrolled ('dumb') EV charging sits on the electricity bus as a fixed
    load. The smart/V2G share of EV demand sits on the EV bus and reaches the
    grid only through the smart_charging links, so it shows up as flexible
    consumption rather than as part of these demand curves.
    """
    loads = n.loads if buses is None else n.loads[n.loads.bus.isin(buses)]
    p_set = n.loads_t.p_set
    base = p_set.reindex(columns=loads.index[loads.carrier == "AC"], fill_value=0.0).sum(axis=1)
    ev = p_set.reindex(columns=loads.index[loads.carrier == "EV_dumb"], fill_value=0.0).sum(axis=1)
    return base, base + ev


def order_columns(df, order):
    cols = [c for c in order if c in df.columns]
    extra = [c for c in df.columns if c not in order]
    return df[cols + extra]


def save_figure(fig, config, name):
    folder = paths(config)["plots"]
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    fig.savefig(path, dpi=config["plotting"]["dpi"], bbox_inches="tight")
    logging.getLogger(__name__).info("saved %s", path.relative_to(ROOT))
    return path

