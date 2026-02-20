"""
US Leading Economic Indicators Dashboard
Adapted from DataVizHonduran/us-leading-indicators for boquin.github.io.

Uses fredapi (not pandas_datareader) — set FRED_API_KEY env var.

Generates a 7-panel dashboard of cyclical leading indicators with
NBER recession shading. Output: reports/leading-indicators/index.html
"""

import os
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from fredapi import Fred

OUTPUT_PATH  = "reports/leading-indicators/index.html"
FRED_API_KEY = os.environ.get('FRED_API_KEY')
if not FRED_API_KEY:
    raise EnvironmentError("FRED_API_KEY environment variable is not set.")

os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
fred = Fred(api_key=FRED_API_KEY)


def get_fred(series_id, years=10):
    """Fetch a single FRED series. Returns a Series with DatetimeIndex."""
    start = date.today() - relativedelta(years=years)
    s = fred.get_series(series_id, observation_start=start)
    return s.dropna()


def get_fred_multi(series_ids, years=10):
    """Fetch multiple FRED series. Returns a DataFrame."""
    start = date.today() - relativedelta(years=years)
    frames = {}
    for sid in series_ids:
        try:
            frames[sid] = fred.get_series(sid, observation_start=start).dropna()
        except Exception as e:
            print(f"  ⚠️  {sid}: {e}")
    return pd.DataFrame(frames)


def add_recession_shading(fig, recession, row, col, y0, y1):
    """Overlay NBER recession bars on a subplot."""
    in_rec = False
    rec_start = None
    for dt, val in recession.items():
        if val == 1 and not in_rec:
            in_rec = True
            rec_start = dt
        elif val == 0 and in_rec:
            in_rec = False
            fig.add_shape(
                type="rect",
                x0=rec_start, x1=dt,
                y0=y0, y1=y1,
                fillcolor="lightgray", opacity=0.5,
                line_width=0, layer="below",
                row=row, col=col
            )
    # Close any open recession at end of data
    if in_rec:
        fig.add_shape(
            type="rect",
            x0=rec_start, x1=recession.index[-1],
            y0=y0, y1=y1,
            fillcolor="lightgray", opacity=0.5,
            line_width=0, layer="below",
            row=row, col=col
        )


def plot_series(fig, row, col, series, recession, y0, y1,
                color='#1f77b4', quantile_line=0.2, y_label=''):
    """Plot a series with optional 20th-pct dashed line and recession shading."""
    series = series.dropna()

    fig.add_trace(go.Scatter(
        x=series.index, y=series.values,
        mode='lines', showlegend=False,
        line=dict(color=color, width=1.8),
    ), row=row, col=col)

    if quantile_line is not None:
        q = series.quantile(quantile_line)
        fig.add_trace(go.Scatter(
            x=series.index, y=[q] * len(series),
            mode='lines', showlegend=False,
            name=f'{int(quantile_line*100)}th pct',
            line=dict(dash='dash', color='gray', width=1),
        ), row=row, col=col)

    add_recession_shading(fig, recession, row, col, y0, y1)
    fig.update_yaxes(range=[y0, y1], title_text=y_label,
                     title_font=dict(size=11), row=row, col=col)
    fig.update_xaxes(title_text='Date', title_font=dict(size=11), row=row, col=col)


def create_dashboard():
    print("Fetching NBER recession data...")
    recession = get_fred("USREC", years=100)

    fig = make_subplots(
        rows=4, cols=2,
        subplot_titles=[
            "Payrolls Diffusion Index (3mma)",
            "Employment-to-Population from 24-Month High",
            "Continuing Claims — % Above 3-Year Low (Inverted)",
            "New Orders from 24-Month High",
            "Building Permits as % of 24-Month High",
            "Mfg Orders-to-Inventories from 24-Month High",
            "Consumer & Activity Diffusion Index (YoY, 3mma)",
            "",
        ],
        vertical_spacing=0.09,
        horizontal_spacing=0.08,
    )

    # ── Chart 1: Payrolls Diffusion Index ────────────────────────────────────
    print("Chart 1: Payrolls Diffusion Index...")
    payroll_ids = [
        "PAYEMS", "USPRIV", "USGOOD", "SRVPRD", "USMINE", "USCONS",
        "MANEMP", "DMANEMP", "NDMANEMP", "USTPU", "USWTRADE", "USTRADE",
        "CES4348400001", "CES4422000001", "USINFO", "USFIRE",
        "USPBS", "USEHS", "USLAH", "USSERV", "USGOVT",
    ]
    df1 = get_fred_multi(payroll_ids, years=100)
    rising = df1.diff().gt(0).astype(int)
    diffusion1 = (rising.sum(axis=1) / rising.shape[1] * 100).rolling(3).mean().dropna()
    plot_series(fig, 1, 1, diffusion1, recession, 0, 100, y_label='% of Industries Rising')

    # ── Chart 2: EPOP from 24-month high ─────────────────────────────────────
    print("Chart 2: Employment-to-Population Ratio...")
    epop = get_fred("EMRATIO", years=100)
    epop_rel = (epop - epop.rolling(24).max()).dropna()
    plot_series(fig, 1, 2, epop_rel, recession, -4, 0, y_label='pp vs 24M High')

    # ── Chart 3: Continuing Claims (inverted) ─────────────────────────────────
    print("Chart 3: Continuing Claims...")
    cc = get_fred("CCSA", years=100)
    cc_rel = (100 - 100 * (cc / cc.rolling(156).min() - 1)).dropna()
    plot_series(fig, 2, 1, cc_rel, recession, 0, 100, y_label='% Above 3Y Low (Inverted)')

    # ── Chart 4: New Orders from 24-month high ────────────────────────────────
    print("Chart 4: New Orders...")
    no = get_fred("NEWORDER", years=50)
    no_rel = (no / no.rolling(24).max()).dropna()
    plot_series(fig, 2, 2, no_rel, recession, 0.65, 1.02, quantile_line=None, y_label='Ratio vs 24M High')

    # ── Chart 5: Building Permits ─────────────────────────────────────────────
    print("Chart 5: Building Permits...")
    permits = get_fred("PERMIT", years=50)
    permits_rel = (permits / permits.rolling(24).max()).dropna()
    plot_series(fig, 3, 1, permits_rel, recession, 0.4, 1.02, quantile_line=None, y_label='Ratio vs 24M High')

    # ── Chart 6: Mfg Orders-to-Inventories ───────────────────────────────────
    print("Chart 6: Mfg Orders-to-Inventories...")
    mfg = get_fred_multi(["AMTMNO", "AMTMTI"], years=50)
    ratio = mfg["AMTMNO"] / mfg["AMTMTI"]
    ratio_rel = (ratio / ratio.rolling(24).max()).dropna()
    plot_series(fig, 3, 2, ratio_rel, recession, 0.7, 1.02, quantile_line=None, y_label='Ratio vs 24M High')

    # ── Chart 7: Consumer & Activity Diffusion Index ─────────────────────────
    # YoY % change > 0 across 8 consumer/activity series = broad spending health
    print("Chart 7: Consumer & Activity Diffusion Index...")
    consumer_ids = {
        "RSAFS":    "Retail Sales",
        "PCEC96":   "Real PCE",
        "DSPIC96":  "Real Disposable Income",
        "UMCSENT":  "UMich Sentiment",
        "AHETPI":   "Avg Hourly Earnings",
        "HOUST":    "Housing Starts",
        "INDPRO":   "Industrial Production",
        "CPILFESL": "Core CPI",
    }
    con_df  = get_fred_multi(list(consumer_ids.keys()), years=30)
    con_yoy = con_df.pct_change(12) * 100
    diffusion7 = ((con_yoy > 0).sum(axis=1) / con_yoy.count(axis=1) * 100
                  ).rolling(3).mean().dropna()
    plot_series(fig, 4, 1, diffusion7, recession, 0, 100, y_label='% of Series with Positive YoY')

    # ── Layout ────────────────────────────────────────────────────────────────
    update_time = datetime.now().strftime('%Y-%m-%d %H:%M UTC')
    fig.update_layout(
        title=dict(
            text="US Leading Economic Indicators",
            x=0.5, xanchor='center',
            font=dict(size=22, color='#1a1a2e')
        ),
        height=1700,
        showlegend=False,
        template='plotly_white',
        margin=dict(t=100, l=55, r=40, b=60),
    )
    # Add footer separately — avoids overwriting subplot title annotations
    fig.add_annotation(
        text=(f'Last Updated: {update_time} | '
              'Source: FRED (St. Louis Fed) | Gray shading = NBER recessions'),
        xref='paper', yref='paper',
        x=0.5, y=-0.02,
        showarrow=False,
        font=dict(size=11, color='gray'),
    )
    # Make subplot titles larger
    fig.update_annotations(font=dict(size=13, color='#1a1a2e'),
                           selector=dict(xref='paper', yref='paper'))
    fig.update_xaxes(showgrid=True, gridwidth=1, gridcolor='#eeeeee')
    fig.update_yaxes(showgrid=True, gridwidth=1, gridcolor='#eeeeee')

    return fig


def main():
    print("=" * 60)
    print("US Leading Indicators Dashboard")
    print("=" * 60)
    fig = create_dashboard()
    fig.write_html(
        OUTPUT_PATH,
        config={'displayModeBar': True, 'displaylogo': False},
    )
    print(f"\n✅ Dashboard saved → {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
