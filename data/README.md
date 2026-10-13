# Input data

Each `input_<year>.xlsx` is a complete PyPSA network for one planning year.
`scripts/solve_network.py` writes every model sheet to a CSV file of the same
name and loads the folder with `pypsa.Network.import_from_csv_folder`, so the
sheets use PyPSA's own table and column names. Component attributes are
documented in the [PyPSA documentation](https://docs.pypsa.org).

`V2G_30/` holds the V2G-30% inputs (70% of EV demand uncontrolled, 30%
flexible with smart charging and V2G). All three scenarios of the paper are
solved from these files; the scenario's `ev_mode` in `config/config.yaml`
adapts the EV fleet at run time:

- `V2G_30`: used as is.
- `SC_30`: the V2G links are removed.
- `Dumb`: 100% of EV demand becomes uncontrolled charging; the smart
  charging, V2G and EV store components are removed.

## Sheets

| Sheet | Read by the model | Content |
|---|---|---|
| `Notes` | no | zone definitions and the CO2 cap trajectory |
| `Techn + Costs` | no | annualised capital cost, marginal cost, efficiency and emission factor per technology |
| `Components` | no | installed capacity and maximum potential per zone and technology |
| `network` | yes | network name and metadata |
| `global_constraints` | yes | annual CO2 cap (`CO2Limit`, t CO2) |
| `buses` | yes | 28 buses: electricity, pumped hydro, hydrogen and EV bus in each zone |
| `carriers` | yes | energy carriers and their CO2 emission factor (t CO2/MWh) |
| `loads` | yes | conventional, uncontrolled EV and flexible EV loads per zone |
| `generators` | yes | power plants, imports and shortage generators |
| `links` | yes | transmission, pumped hydro in/out, electrolysers, fuel cells, smart charging and V2G |
| `stores` | yes | pumped hydro reservoirs, hydrogen storage, EV batteries |
| `storage_units` | yes | stationary batteries |
| `snapshots` | yes | 8760 hourly time stamps of the year |
| `loads-p_set` | yes | hourly demand of every load (MW) |
| `generators-p_max_pu` | yes | hourly capacity factors of wind, PV, run-of-river and geothermal |
| `links-p_max_pu` | yes | hourly share of EVs plugged in, limiting `smart_charging` and `V2G` |

Time-series sheets must have exactly 8760 data rows. PyPSA matches them to
the snapshots by position, so the solver script checks the row count and the
sheet names before solving.

## Units

| Quantity | Unit |
|---|---|
| Power capacity (`p_nom`, `p_nom_min`, `p_nom_max`) | MW |
| Energy capacity (`e_nom`, ...) | MWh |
| `capital_cost` | EUR/MW/year or EUR/MWh/year (annualised) |
| `marginal_cost` | EUR/MWh |
| `efficiency` | per unit |
| `standing_loss` | per unit per hour |
| `co2_emissions` | t CO2 per MWh of primary energy |
| `p_set` | MW |
| `p_max_pu` | per unit |

## Naming

Components are named `<zone>_<technology>`, for example `R3_wind_pp`,
`R1_bus_el`, `R6_V2G`. Transmission links are directional:
`R1_R2_powerline` carries power from R1 to R2.

| Zone | Name | Regions |
|---|---|---|
| R1 | North | Valle d'Aosta, Piemonte, Liguria, Lombardia, Trentino-Alto Adige, Veneto, Friuli-Venezia Giulia, Emilia-Romagna |
| R2 | Centre-North | Toscana, Marche |
| R3 | Centre-South | Lazio, Abruzzo, Umbria, Campania |
| R4 | South | Molise, Puglia, Basilicata |
| R5 | Sardinia | Sardegna |
| R6 | Sicily | Sicilia |
| R7 | Calabria | Calabria |

## Year-by-year overview

| Year | CO2 cap (Mt) | EV demand (TWh) | EV battery store, all zones (GWh) | Smart-charging / V2G link capacity, all zones (GW) |
|---|---|---|---|---|
| 2025 | 67.1 | 3.1 | 21.9 | 5.4 |
| 2030 | 53.7 | 13.4 | 93.7 | 23.1 |
| 2035 | 40.3 | 36.8 | 258.0 | 63.6 |
| 2040 | 26.9 | 60.6 | 424.8 | 104.8 |
| 2045 | 13.4 | 68.5 | 480.0 | 118.4 |
| 2050 | 0.0 | 68.5 | 480.0 | 118.4 |

In every year 70% of EV energy demand is uncontrolled (`*_load_EV_dumb`) and
30% is flexible (`*_load_EV_smart`). The split is already applied in
`loads-p_set`, and both parts use the same hourly charging profile. In the
`Dumb` scenario the solver script adds the flexible part back to the
uncontrolled load. Conventional electricity demand is the same in all years
(319.7 TWh). Technology costs fall over time following the `Techn + Costs`
sheet of each workbook.

The extendable flags in the workbooks are not used. The solver script sets
them from `extendable` in `config/config.yaml`.

## Adding a scenario

1. Copy `V2G_30/` to a new folder, e.g. `data/V2G_50/`.
2. Edit the workbooks, for example change the split between the
   `*_EV_dumb` and `*_EV_smart` columns of `loads-p_set` (and the matching
   EV store and link sizes).
3. Add the scenario to `config/config.yaml`:

   ```yaml
   scenarios:
     V2G_50:
       data: V2G_50
       ev_mode: v2g
   ```

4. Run `python scripts/solve_network.py --scenario V2G_50`.

Keep the formulas in the documentation sheets intact if you edit with Excel.
If you edit with Python, change only the model sheets.
