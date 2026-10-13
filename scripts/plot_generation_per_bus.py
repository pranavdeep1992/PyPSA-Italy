"""Annual electricity production per bidding zone, with the zone's demand as a dot.

One panel per zone, one stacked bar per year. As in the national generation
mix, variable renewables are counted at their available output (curtailment
included) unless --dispatched is given. Demand is the zone's conventional
load plus uncontrolled EV charging; the gap between bars and dot is covered
by trade with the other zones, storage and curtailment.

    python scripts/plot_generation_per_bus.py
    python scripts/plot_generation_per_bus.py --scenario Dumb --dispatched
"""

import argparse

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from _helpers import (
    add_common_args, COLORS, LABELS, SUPPLY_ORDER, ZONES, demand, load_config,
    load_network, order_columns, paths, save_figure, setup_logging, solved_years,
    supply_by_carrier,
)
from plot_generation_mix import PLOTTED

Y_MAX_TWH = 350


def zone_energy(n, zone, curtailed):
    """Annual production per carrier and demand of one zone, TWh."""
    bus = [f"{zone}_bus_el"]
    weights = n.snapshot_weightings.generators
    energy = weights @ supply_by_carrier(n, curtailed, bus) / 1e6
    energy["demand"] = weights @ demand(n, bus)[1] / 1e6
    return energy


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    add_common_args(parser)
    parser.add_argument("--dispatched", action="store_true",
                        help="count renewables at actual output instead of available output")
    args = parser.parse_args()

    setup_logging()
    config = load_config(args.config, args.scenario)
    years = solved_years(config)
    networks = {y: load_network(config, y) for y in years}

    table = pd.concat({
        zone: pd.DataFrame({y: zone_energy(n, zone, not args.dispatched) for y, n in networks.items()}).T
        for zone in ZONES
    }).fillna(0)
    out = paths(config)["summary"]
    out.mkdir(parents=True, exist_ok=True)
    table.rename_axis(["zone", "year"]).round(3).to_csv(out / "annual_energy_per_zone_TWh.csv")

    fig, axes = plt.subplots(nrows=len(ZONES), ncols=1, figsize=(15, 55))
    for ax, (zone, name) in zip(axes, ZONES.items()):
        data = table.loc[zone]
        bars = order_columns(data[[c for c in PLOTTED if c in data]], SUPPLY_ORDER)
        bars = bars.loc[:, bars.sum() > 0]
        bars.plot.bar(stacked=True, ax=ax, color=[COLORS[c] for c in bars], legend=False)
        ax.scatter(np.arange(len(data)), data["demand"], color="red", s=100, zorder=5,
                   label="demand")

        ax.set_title(f"{zone} - {name}", fontsize=35)
        ax.set_xticklabels([str(y) for y in data.index], fontsize=25, rotation=45)
        ax.set_ylabel("Energy [TWh]", fontsize=35)
        ax.tick_params(axis="y", labelsize=25)
        ax.set_ylim(0, Y_MAX_TWH)

    # One legend for all panels, covering every source that appears anywhere.
    shown = [c for c in SUPPLY_ORDER if c in PLOTTED and c in table and table[c].sum() > 0]
    handles = [plt.Rectangle((0, 0), 1, 1, color=COLORS[c]) for c in shown]
    handles.append(plt.Line2D([0], [0], marker="o", color="w", markerfacecolor="red", markersize=14))
    axes[-1].legend(handles, [LABELS[c] for c in shown] + ["Total demand"],
                    title="Sources and demand", bbox_to_anchor=(0.5, -0.3), loc="upper center",
                    ncol=4, fontsize=20, title_fontsize=25)

    fig.suptitle(f"{config['scenario']} - generation per zone", fontsize=45, y=1.0)
    fig.tight_layout()
    name = "generation_per_bus_dispatched.png" if args.dispatched else "generation_per_bus.png"
    save_figure(fig, config, name)
    plt.close(fig)


if __name__ == "__main__":
    main()
