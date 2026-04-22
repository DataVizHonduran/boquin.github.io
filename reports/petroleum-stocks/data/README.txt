EIA Weekly Petroleum Stocks — Data Directory
=============================================
Source: EIA Weekly Petroleum Status Report, via EIA Open Data API v2
Endpoint: https://api.eia.gov/v2/petroleum/stoc/wstk/data/
Updated: every Wednesday by ~10:30 AM ET
Unit: Million Barrels (MMBbl) throughout

PRODUCTS COVERED
----------------
- Crude Oil       (EIA product code: EPC0, process: SAX ex-SPR, fallback SAE)
- Motor Gasoline  (EIA product code: EPM0, process: SAE)
- Distillate Fuel Oil (EIA product code: EPD0, process: SAE — includes heating oil and diesel)

Note: Crude uses SAX (excluding Strategic Petroleum Reserve) to avoid ~600 MMBbl
SPR distortion, especially in PADD 3 (Gulf Coast).

GEOGRAPHIES (duoarea)
---------------------
NUS  — U.S. Total
R10  — PADD 1 (East Coast)
R20  — PADD 2 (Midwest)
R30  — PADD 3 (Gulf Coast) — largest storage hub in the U.S.
R40  — PADD 4 (Rocky Mountain)
R50  — PADD 5 (West Coast)

FILES
-----
{product}_raw.csv
  Columns: date, duoarea, value_mmbbl
  Coverage: ~7 years of weekly history for all 6 geographies (long format)
  Use for: trend analysis, year-over-year comparisons, historical context

{product}_seasonal.csv
  Columns: date, duoarea, value_mmbbl, seasonal_lo, seasonal_hi, pct_of_range
  Coverage: last 365 days only (long format)
  Use for: current positioning vs seasonal norms, supply tightness signals

  seasonal_lo   — minimum value for that calendar week over the prior 5 years
  seasonal_hi   — maximum value for that calendar week over the prior 5 years
  pct_of_range  — where current stocks sit within the 5-yr band:
                    0   = at the 5-year low (historically tight supply)
                    100 = at the 5-year high (historically large surplus)
                    50  = middle of the range

INTERPRETATION NOTES
--------------------
- Builds (week-over-week increases) are bearish for prices; draws are bullish.
- pct_of_range below ~20 signals historically tight supply for that week.
- pct_of_range above ~80 signals historically elevated inventories.
- PADD 3 (Gulf Coast) dominates crude storage and is most watched by traders.
- Distillate stocks are sensitive to heating demand (winter) and diesel (trucking/exports).
- Motor gasoline stocks peak in late winter ahead of summer driving season.
