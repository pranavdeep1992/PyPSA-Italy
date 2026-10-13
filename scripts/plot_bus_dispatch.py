"""Hourly electricity balance of a single bidding zone.

Supply (local generation, imports, storage discharge, V2G) is stacked as
areas. Above the demand line sit the flexible loads and the exports, so the
top of the hatched bands equals the top of the supply stack in every hour.
Generators are shown at actual dispatch, i.e. without curtailed energy.

    python scripts/plot_bus_dispatch.py --zone R1 --year 2040
    python scripts/plot_bus_dispatch.py --zone R6 --year 2050 --start 07-08 --end 07-14
    python scripts/plot_bus_dispatch.py --all-zones --year 2040
"""

import argparse
import logging

import matplotlib.pyplot as plt
import pandas as pd

from _helpers import (
    add_common_args, CHARGING_ORDER, COLORS, LABELS, SUPPLY_ORDER, ZONES, demand, link_flow,
    load_config, load_network, order_columns, save_figure, setup_logging,
    storage_flows, sum_by,
)

logger = logging.getLogger(__name__)
HATCH = {"smart_charging": "\\\\\\\\", "exports": "||"}


def zone_balance(n, zone):
    """Supply, demand and flexible consumption at one zone's electricity bus, GW."""
    bus = [f"{zone}_bus_el"]
    gens = n.generators.index[n.generators.bus.isin(bus)]
    battery_out, battery_in = storage_flows(n, bus)

    supply = sum_by(n.generators_t.p[gens], n.generators.carrier[gens]).assign(
        imports=link_flow(n, "AC", "p1", bus),
        phs_discharging=link_flow(n, "phs_discharging", "p1", bus),
        battery_discharging=battery_out,
        fuel_cell=link_flow(n, "fuel_cell", "p1", bus),
        V2G=link_flow(n, "V2G", "p1", bus),
    )
    # Solver tolerances leave values like -1e-9 that would break the stacked areas.
    supply = supply.clip(lower=0)
    supply = order_columns(supply.loc[:, supply.sum() > 0], SUPPLY_ORDER) / 1e3

    charging = pd.DataFrame({
        "phs_charging": link_flow(n, "phs_charging", "p0", bus),
        "battery_charging": battery_in,
        "electrolyser": link_flow(n, "electrolyser", "p0", bus),
        "smart_charging": link_flow(n, "smart_charging", "p0", bus),
        "exports": link_flow(n, "AC", "p0", bus),
    }).clip(lower=0) / 1e3

    base, total = demand(n, bus)
    base, total = base / 1e3, total / 1e3

    mismatch = (supply.sum(axis=1) - total - charging.sum(axis=1)).abs().max()
    if mismatch > 1e-3:
        logger.warning("%s: energy balance off by up to %.4f GW", zone, mismatch)
    return supply, base, total, charging


def plot_zone(n, zone, year, start, end):
    supply, base, total, charging = zone_balance(n, zone)
    window = slice(f"{year}-{start}", f"{year}-{end}")

    fig, ax = plt.subplots(figsize=(15, 8))
    supply.loc[window].plot.area(ax=ax, stacked=True, linewidth=0,
                                 color=[COLORS[c] for c in supply], legend=False)
    total.loc[window].plot(ax=ax, linewidth=2, color="black", label="Total demand")
    base.loc[window].plot(ax=ax, linewidth=2, color="#3B0C04", label="Electric sector demand")

    lower = total.loc[window]
    for name in CHARGING_ORDER:
        if charging.loc[window, name].abs().sum() == 0:
            continue
        upper = lower + charging.loc[window, name]
        ax.fill_between(lower.index, lower, upper, color=COLORS[name], alpha=0.5,
                        hatch=HATCH.get(name, "////"), edgecolor="black", linewidth=1,
                        label=name)
        lower = upper

    handles, keys = ax.get_legend_handles_labels()
    ax.legend(handles, [LABELS.get(k, k) for k in keys], loc="upper left",
              bbox_to_anchor=(1.02, 1.0), fontsize=12)
    ax.set_xlabel("")
    ax.set_ylabel("Electric power (GW)", fontsize=16)
    ax.set_title(f"Hourly electricity balance, {zone} ({ZONES[zone]}), {year}", fontsize=18)
    ax.set_ylim(bottom=0)
    return fig


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    add_common_args(parser)
    parser.add_argument("--year", type=int, default=2040)
    zones = parser.add_mutually_exclusive_group()
    zones.add_argument("--zone", choices=list(ZONES), default="R1")
    zones.add_argument("--all-zones", action="store_true")
    parser.add_argument("--start", default="01-10", help="first day, MM-DD")
    parser.add_argument("--end", default="01-10", help="last day, MM-DD (inclusive)")
    args = parser.parse_args()

    setup_logging()
    config = load_config(args.config, args.scenario)
    n = load_network(config, args.year)

    for zone in ZONES if args.all_zones else [args.zone]:
        fig = plot_zone(n, zone, args.year, args.start, args.end)
        save_figure(fig, config, f"balance_{zone}_{args.year}_{args.start}_{args.end}.png")
        plt.close(fig)


if __name__ == "__main__":
    main()
