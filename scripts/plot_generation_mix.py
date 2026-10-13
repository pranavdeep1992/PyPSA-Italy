"""Annual electricity production by source for every solved year.

Variable renewables are counted at their available output, so curtailed
energy is included in the bars. Two markers show total demand (conventional
load plus uncontrolled EV charging) and the conventional load alone.

    python scripts/plot_generation_mix.py
"""

import argparse

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from _helpers import (
    add_common_args, COLORS, LABELS, SUPPLY_ORDER, demand, link_flow, load_config, load_network,
    order_columns, paths, save_figure, setup_logging, solved_years, storage_flows,
    supply_by_carrier,
)

# Sources drawn as bars. Storage and V2G only shift energy in time, so they
# are kept in the CSV table but not stacked here.
PLOTTED = [
    "coal", "natural_gas", "biomass", "geothermal", "reservoir_hydro", "rh_hydro",
    "AC_import", "wind", "pv_rooftop", "pv_agri", "pv_utility",
]


def annual_energy(n):
    """Annual energy per source and demand type in TWh."""
    hourly = supply_by_carrier(n, curtailed=True)
    base_load, total_load = demand(n)
    battery_out, battery_in = storage_flows(n)

    hourly = hourly.assign(
        total_demand=total_load,
        electric_sector_demand=base_load,
        battery_discharging=battery_out,
        battery_charging=battery_in,
        phs_discharging=link_flow(n, "phs_discharging", "p1"),
        phs_charging=link_flow(n, "phs_charging", "p0"),
        electrolyser=link_flow(n, "electrolyser", "p0"),
        fuel_cell=link_flow(n, "fuel_cell", "p1"),
        smart_charging=link_flow(n, "smart_charging", "p0"),
        V2G=link_flow(n, "V2G", "p1"),
    )
    return n.snapshot_weightings.generators @ hourly / 1e6


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    add_common_args(parser)
    args = parser.parse_args()

    setup_logging()
    config = load_config(args.config, args.scenario)
    years = solved_years(config)

    energy = pd.DataFrame({y: annual_energy(load_network(config, y)) for y in years}).T.fillna(0)

    out = paths(config)["summary"]
    out.mkdir(parents=True, exist_ok=True)
    energy.round(3).to_csv(out / "annual_energy_TWh.csv", index_label="year")

    bars = order_columns(energy[[c for c in PLOTTED if c in energy]], SUPPLY_ORDER)
    bars = bars.loc[:, bars.sum() > 0]

    fig, ax = plt.subplots(figsize=(10, 8))
    bars.plot.bar(stacked=True, ax=ax, color=[COLORS[c] for c in bars], width=0.7)

    x = np.arange(len(energy))
    ax.scatter(x, energy["total_demand"], color="red", zorder=5, label="total_demand")
    ax.scatter(x, energy["electric_sector_demand"], color="#691708", zorder=5,
               label="electric_sector_demand")

    names = {**LABELS, "total_demand": "Total demand",
             "electric_sector_demand": "Electric sector demand"}
    handles, keys = ax.get_legend_handles_labels()
    ax.legend(handles, [names[k] for k in keys], title="Sources", loc="upper left",
              fontsize=12, ncol=2)

    ax.set_xticklabels([str(y) for y in energy.index], fontsize=18, rotation=45)
    ax.set_ylabel("Electricity produced [TWh]", fontsize=20)
    ax.set_title(f"{config['scenario']} - electricity production", fontsize=25)
    ax.tick_params(axis="y", labelsize=15)
    ax.set_ylim(0, config["case"].get("generation_mix_ymax"))
    ax.spines[["right", "top"]].set_visible(False)

    save_figure(fig, config, "generation_mix.png")
    plt.close(fig)


if __name__ == "__main__":
    main()
