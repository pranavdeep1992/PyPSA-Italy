"""Average daily shape of the load a zone draws from the grid.

Net grid load = conventional load + uncontrolled EV charging + smart
charging - V2G feed-in, all at the zone's electricity bus. The script
averages it by hour of day over workdays and weekends of one season and
normalises each curve by its peak, which shows how the charging strategy
reshapes the daily profile. Pass several scenarios to compare them.

    python scripts/plot_grid_load_profile.py --scenario SC_30
    python scripts/plot_grid_load_profile.py --scenario Dumb SC_30 V2G_30 --zone R1 --year 2040
"""

import argparse
import logging

import matplotlib.pyplot as plt

from _helpers import (
    ROOT, ZONES, demand, link_flow, load_config, load_network, paths, setup_logging,
)

SEASONS = {"winter": [12, 1, 2], "spring": [3, 4, 5], "summer": [6, 7, 8], "autumn": [9, 10, 11]}


def net_grid_load(n, zone):
    bus = [f"{zone}_bus_el"]
    return (
        demand(n, bus)[1]
        + link_flow(n, "smart_charging", "p0", bus)
        - link_flow(n, "V2G", "p1", bus)
    )


def daily_profile(series, months, weekend):
    idx = series.index
    mask = idx.month.isin(months) & ((idx.weekday >= 5) == weekend)
    profile = series[mask].groupby(idx[mask].hour).mean()
    peak = profile.abs().max()
    return profile / peak if peak else profile


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--config")
    parser.add_argument("--scenario", nargs="+", help="one or more scenarios (default: the one in the config)")
    parser.add_argument("--zone", choices=list(ZONES), default="R1")
    parser.add_argument("--year", type=int, default=2040)
    parser.add_argument("--season", choices=list(SEASONS), default="winter")
    args = parser.parse_args()

    setup_logging()
    configs = [load_config(args.config, s) for s in (args.scenario or [None])]

    fig, axes = plt.subplots(1, 2, figsize=(10, 2.6), dpi=180, constrained_layout=True)
    for config in configs:
        load = net_grid_load(load_network(config, args.year), args.zone)
        for ax, weekend in zip(axes, (False, True)):
            profile = daily_profile(load, SEASONS[args.season], weekend)
            ax.plot(profile.index, profile.values, linewidth=2, label=config["scenario"])

    for ax, title in zip(axes, ("Workday", "Weekend")):
        ax.set_title(f"{title}, {args.season}", fontsize=14, pad=6)
        ax.set_xlim(0, 23)
        ax.set_ylim(0, 1.05)
        ax.set_xticks([0, 6, 12, 18, 23])
        ax.set_xlabel("Hour of day")
        ax.set_ylabel("Normalised power", fontsize=12)
        ax.grid(True, alpha=0.3, linestyle=":")
    axes[1].legend(loc="lower right", frameon=True, title=f"Net grid load, {args.zone}")
    fig.suptitle(f"{args.zone} ({ZONES[args.zone]}), {args.year}", fontsize=14)

    names = [c["scenario"] for c in configs]
    folder = paths(configs[0])["plots"] if len(configs) == 1 else ROOT / "results" / "comparison"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"grid_load_profile_{'_'.join(names)}_{args.zone}_{args.year}_{args.season}.png"
    fig.savefig(path, dpi=configs[0]["plotting"]["dpi"], bbox_inches="tight")
    plt.close(fig)
    logging.getLogger(__name__).info("saved %s", path.relative_to(ROOT))


if __name__ == "__main__":
    main()
