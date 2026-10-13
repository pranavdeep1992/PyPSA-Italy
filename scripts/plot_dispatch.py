"""Hourly national dispatch for one winter and one summer week of every year.

Coloured areas are supply. The two lines are demand (with and without
uncontrolled EV charging). Hatched bands stacked above the demand line are
flexible consumption: pumped hydro, batteries, electrolysers and smart EV
charging.

    python scripts/plot_dispatch.py
    python scripts/plot_dispatch.py --dispatched     # renewables at actual output
"""

import argparse

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from _helpers import (
    add_common_args, CHARGING_ORDER, COLORS, LABELS, SUPPLY_ORDER, demand, link_flow, load_config,
    load_network, order_columns, save_figure, setup_logging, solved_years,
    storage_flows, supply_by_carrier,
)

Y_MAX_GW = 80
HATCH = {"smart_charging": "\\\\\\\\"}  # everything else uses "////"


def dispatch_frames(n, curtailed=True):
    """Supply, demand and flexible consumption in GW, hourly."""
    battery_out, battery_in = storage_flows(n)

    supply = supply_by_carrier(n, curtailed).assign(
        phs_discharging=link_flow(n, "phs_discharging", "p1"),
        battery_discharging=battery_out,
        fuel_cell=link_flow(n, "fuel_cell", "p1"),
        V2G=link_flow(n, "V2G", "p1"),
    )
    # Solver tolerances leave values like -1e-9 that would break the stacked areas.
    supply = supply.clip(lower=0)
    supply = order_columns(supply.loc[:, supply.sum() > 0], SUPPLY_ORDER) / 1e3

    charging = pd.DataFrame({
        "phs_charging": link_flow(n, "phs_charging", "p0"),
        "battery_charging": battery_in,
        "electrolyser": link_flow(n, "electrolyser", "p0"),
        "smart_charging": link_flow(n, "smart_charging", "p0"),
    }).clip(lower=0) / 1e3

    base, total = demand(n)
    return supply, base / 1e3, total / 1e3, charging


def draw_week(ax, supply, base, total, charging, start, end):
    week = slice(start, end)
    supply.loc[week].plot.area(ax=ax, stacked=True, linewidth=0,
                               color=[COLORS[c] for c in supply], legend=False)
    total.loc[week].plot(ax=ax, linewidth=2, color="black")
    base.loc[week].plot(ax=ax, linewidth=2, color="#3B0C04")

    # Stack charging bands on top of total demand, bottom to top.
    lower = total.loc[week]
    for name in CHARGING_ORDER:
        if name not in charging or charging[name].abs().sum() == 0:
            continue
        upper = lower + charging.loc[week, name]
        ax.fill_between(lower.index, lower, upper, color=COLORS[name],
                        hatch=HATCH.get(name, "////"), edgecolor="black", linewidth=1)
        lower = upper

    ax.set_xlabel("")
    ax.set_ylabel("Power (GW)", fontsize=20)
    ax.tick_params(axis="y", labelsize=15)
    ax.tick_params(axis="x", which="both", labelsize="large")
    ax.set_ylim(0, Y_MAX_GW)


def legend_handles(supply_columns, charging_columns):
    sources = [Patch(facecolor=COLORS[c], label=LABELS[c]) for c in supply_columns]
    sources += [
        Patch(facecolor=COLORS[c], edgecolor="black", hatch=HATCH.get(c, "////"), label=LABELS[c])
        for c in charging_columns
    ]
    demand_lines = [
        Line2D([0], [0], color="black", lw=3, label="Total demand"),
        Line2D([0], [0], color="#3B0C04", lw=3, label="Electric sector demand"),
    ]
    return sources, demand_lines


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    add_common_args(parser)
    parser.add_argument("--years", nargs="+", type=int)
    parser.add_argument("--dispatched", action="store_true",
                        help="show renewables at actual output instead of available output")
    args = parser.parse_args()

    setup_logging()
    config = load_config(args.config, args.scenario)
    years = args.years or solved_years(config)
    winter, summer = config["plotting"]["winter_week"], config["plotting"]["summer_week"]

    fig, axes = plt.subplots(len(years), 2, figsize=(25, 5 * len(years)), squeeze=False)
    supply_seen, charging_seen = set(), set()

    for (ax_w, ax_s), year in zip(axes, years):
        supply, base, total, charging = dispatch_frames(load_network(config, year),
                                                        curtailed=not args.dispatched)
        draw_week(ax_w, supply, base, total, charging, f"{year}-{winter[0]}", f"{year}-{winter[1]}")
        draw_week(ax_s, supply, base, total, charging, f"{year}-{summer[0]}", f"{year}-{summer[1]}")
        ax_w.set_title(f"Winter {year}", fontsize=20)
        ax_s.set_title(f"Summer {year}", fontsize=20)
        supply_seen.update(supply.columns)
        charging_seen.update(c for c in charging if charging[c].abs().sum() > 0)

    sources, demand_lines = legend_handles(
        [c for c in SUPPLY_ORDER if c in supply_seen],
        [c for c in CHARGING_ORDER if c in charging_seen],
    )
    fig.tight_layout(h_pad=1, w_pad=2)
    fig.subplots_adjust(hspace=0.5, top=0.95)
    fig.legend(handles=sources, loc="upper center", bbox_to_anchor=(0.5, 0.0),
               ncol=6, fontsize=20, title="Sources", title_fontsize=25)
    fig.legend(handles=demand_lines, loc="upper center",
               bbox_to_anchor=(0.5, -0.03 * 6 / len(years) - 0.05),
               ncol=2, fontsize=20, title="Demand", title_fontsize=25)

    name = "dispatch_weeks_dispatched.png" if args.dispatched else "dispatch_weeks.png"
    save_figure(fig, config, name)
    plt.close(fig)


if __name__ == "__main__":
    main()
