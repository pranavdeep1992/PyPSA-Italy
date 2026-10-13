"""Optimal capacities per bidding zone over the planning years.

Writes three figures, one panel per zone:
  capacity_renewables_per_bus.png   wind and PV, GW
  capacity_battery_per_bus.png      stationary batteries, GWh
  capacity_ev_store_per_bus.png     EV battery store available to the grid, GWh

    python scripts/plot_capacity_per_bus.py
"""

import argparse

import matplotlib.pyplot as plt
import pandas as pd

from _helpers import (
    add_common_args, COLORS, LABELS, ZONES, load_config, load_network, paths, save_figure,
    setup_logging, solved_years, zone_of,
)

RENEWABLES = ["wind", "pv_rooftop", "pv_utility", "pv_agri"]


def capacities(n):
    """Optimal capacity per zone and technology for one year (GW or GWh)."""
    gen = n.generators[n.generators.carrier.isin(RENEWABLES)]
    su = n.storage_units[n.storage_units.carrier == "battery"]
    ev = n.stores[n.stores.carrier == "EV_store"]

    def by_zone(values, df):
        return values.groupby([df.bus.map(zone_of), df.carrier]).sum() / 1e3

    return pd.concat([
        by_zone(gen.p_nom_opt, gen),
        by_zone(su.p_nom_opt * su.max_hours, su),   # energy capacity
        by_zone(ev.e_nom_opt, ev),
    ])


def plot_panels(table, carriers, title, ylabel, ymax):
    """One bar chart per zone; ``table`` has (zone, carrier) rows and year columns."""
    fig, axes = plt.subplots(nrows=len(ZONES), ncols=1, figsize=(10, 40))
    for ax, (zone, name) in zip(axes, ZONES.items()):
        rows = pd.MultiIndex.from_product([[zone], carriers])
        data = table.reindex(rows).droplevel(0).fillna(0)
        data.T.plot.bar(ax=ax, color=[COLORS[c] for c in carriers],
                        width=0.8 if len(carriers) > 1 else 0.5, legend=False)
        ax.set_title(f"{zone} - {name}", fontsize=25)
        ax.set_xlabel("Year", fontsize=25)
        ax.set_ylabel(ylabel, fontsize=25)
        ax.tick_params(axis="x", labelrotation=45, labelsize=25)
        ax.tick_params(axis="y", labelsize=25)
        ax.set_ylim(0, ymax)

    handles, keys = axes[-1].get_legend_handles_labels()
    axes[-1].legend(handles, [LABELS[k] for k in keys], title="Sources", fontsize=18,
                    title_fontsize=20, loc="upper center", bbox_to_anchor=(0.5, -0.45), ncol=4)
    fig.suptitle(title, fontsize=40, y=1)
    fig.tight_layout()
    return fig


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    add_common_args(parser)
    args = parser.parse_args()

    setup_logging()
    config = load_config(args.config, args.scenario)
    scenario = config["scenario"]
    years = solved_years(config)

    table = pd.DataFrame({y: capacities(load_network(config, y)) for y in years})
    out = paths(config)["summary"]
    out.mkdir(parents=True, exist_ok=True)
    table = table.rename_axis(["zone", "carrier"])
    table.round(3).to_csv(out / "capacity_per_zone_GW_GWh.csv")

    figures = [
        (RENEWABLES, "Generators optimal capacity per zone", "Optimal capacity [GW]", 200,
         "capacity_renewables_per_bus.png"),
        (["battery"], "Battery optimal capacity per zone", "Optimal capacity [GWh]", 450,
         "capacity_battery_per_bus.png"),
        (["EV_store"], "EV store capacity per zone", "Optimal capacity [GWh]", 450,
         "capacity_ev_store_per_bus.png"),
    ]
    present = set(table.index.get_level_values("carrier"))
    for carriers, title, ylabel, ymax, filename in figures:
        if not present.intersection(carriers):
            continue  # e.g. no EV store in the uncontrolled-charging scenario
        fig = plot_panels(table, carriers, f"{scenario} - {title}", ylabel, ymax)
        save_figure(fig, config, filename)
        plt.close(fig)


if __name__ == "__main__":
    main()
