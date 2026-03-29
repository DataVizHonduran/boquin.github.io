"""
Brazil DPF Debt Holders Dashboard
Generates an 8-panel Plotly chart (2 rows × 4 cols) showing:
  Row 1: R$ billions by holder type
  Row 2: % of total DPF by holder type
Source: Relatório Mensal da Dívida (RMD) — Tesouro Nacional
"""

import io
import os
import sys
import zipfile

import pandas as pd
import plotly.graph_objects as go
import requests
from plotly.subplots import make_subplots

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
ZIP_URL = "https://thot-arquivos.tesouro.gov.br/publicacao-anexo/27925"
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "reports", "brasil-debt-holders")
OUT_FILE = os.path.join(OUT_DIR, "index.html")

# Wong (2011) colorblind-safe palette
COLORS = {
    "banks":      "#0072B2",
    "funds":      "#009E73",
    "pensions":   "#D55E00",
    "foreigners": "#CC79A7",
}

HOLDERS = [
    ("banks",      "Instituições Financeiras", "Banks"),
    ("funds",      "Fundos de Investimento",   "Funds"),
    ("pensions",   "Previdência",               "Pensions"),
    ("foreigners", "Não-residentes",            "Foreigners"),
]

# Column indices in sheet 2.7 (0-based)
# Col 0 = Date; pairs are (brl_col, pct_col)
COL_MAP = {
    "banks":      (1, 2),
    "funds":      (3, 4),
    "pensions":   (5, 6),
    "foreigners": (7, 8),
    "total_brl":  15,
}


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
def fetch_data():
    print("Fetching ZIP from Tesouro Nacional...", flush=True)
    resp = requests.get(ZIP_URL, timeout=120)
    resp.raise_for_status()

    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    xlsx_name = next(n for n in zf.namelist() if n.endswith(".xlsx"))
    print(f"  Parsing: {xlsx_name}", flush=True)

    xl = pd.ExcelFile(zf.open(xlsx_name))
    sheet = next(s for s in xl.sheet_names if "2.7" in s)
    raw = xl.parse(sheet, header=None)

    # Data rows start at index 5 (row 4 is header, rows 0-3 are title/blank)
    data = raw.iloc[5:].copy()
    data.columns = range(data.shape[1])

    # Parse dates
    dates = pd.to_datetime(data[0], errors="coerce")
    data = data[dates.notna()].copy()
    dates = dates[dates.notna()]

    df = pd.DataFrame(index=dates)
    df.index.name = "date"

    for key, (brl_col, pct_col) in [(k, v) for k, v in COL_MAP.items() if k != "total_brl"]:
        df[f"{key}_brl"] = pd.to_numeric(data[brl_col].values, errors="coerce")
        df[f"{key}_pct"] = pd.to_numeric(data[pct_col].values, errors="coerce") * 100

    df["total_brl"] = pd.to_numeric(data[COL_MAP["total_brl"]].values, errors="coerce")

    df = df.sort_index().dropna(how="all")
    print(f"  Loaded {len(df)} monthly observations: {df.index[0]:%b %Y} – {df.index[-1]:%b %Y}")
    return df


# ---------------------------------------------------------------------------
# Chart
# ---------------------------------------------------------------------------
def build_chart(df):
    subtitle_titles = []
    for key, pt_label, en_label in HOLDERS:
        subtitle_titles.append(f"<b>{en_label}</b><br><span style='font-size:11px;color:#666'>{pt_label}</span>")
    # Row 2 gets blank subplot titles (row label handles it)
    subtitle_titles += [""] * 4

    fig = make_subplots(
        rows=2,
        cols=4,
        shared_xaxes=True,
        vertical_spacing=0.12,
        horizontal_spacing=0.06,
        subplot_titles=subtitle_titles,
    )

    for col_idx, (key, pt_label, en_label) in enumerate(HOLDERS, start=1):
        color = COLORS[key]
        latest_date = df.index[-1]

        # --- Row 1: R$ Billions ---
        brl = df[f"{key}_brl"]
        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=brl,
                mode="lines",
                line=dict(color=color, width=2),
                name=en_label,
                showlegend=False,
                hovertemplate="%{x|%b %Y}<br><b>R$ %{y:,.0f}bn</b><extra></extra>",
            ),
            row=1,
            col=col_idx,
        )
        # Latest-value annotation
        fig.add_annotation(
            x=latest_date,
            y=brl.iloc[-1],
            text=f"<b>R${brl.iloc[-1]:,.0f}bn</b>",
            xanchor="right",
            yanchor="bottom",
            showarrow=False,
            font=dict(size=10, color=color),
            row=1,
            col=col_idx,
        )

        # --- Row 2: % of Total ---
        pct = df[f"{key}_pct"]
        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=pct,
                mode="lines",
                line=dict(color=color, width=2),
                name=en_label,
                showlegend=False,
                hovertemplate="%{x|%b %Y}<br><b>%{y:.1f}%</b><extra></extra>",
            ),
            row=2,
            col=col_idx,
        )
        fig.add_annotation(
            x=latest_date,
            y=pct.iloc[-1],
            text=f"<b>{pct.iloc[-1]:.1f}%</b>",
            xanchor="right",
            yanchor="bottom",
            showarrow=False,
            font=dict(size=10, color=color),
            row=2,
            col=col_idx,
        )

    # Row axis labels via annotations on the left edge
    for row, label in [(1, "R$ Billions"), (2, "% of Total DPF")]:
        fig.add_annotation(
            text=f"<b>{label}</b>",
            xref="paper",
            yref="paper",
            x=-0.02,
            y=0.75 if row == 1 else 0.22,
            showarrow=False,
            font=dict(size=11, color="#444"),
            textangle=-90,
        )

    last_date_str = df.index[-1].strftime("%B %Y")
    fig.update_layout(
        title=dict(
            text=(
                f"<b>Holders of Brazil's Federal Public Debt (DPF)</b>"
                f"<br><span style='font-size:13px;color:#666'>"
                f"Monthly, R$ Billions and % of Total | Jan 2007 – {last_date_str}"
                f"</span>"
            ),
            x=0.5,
            xanchor="center",
            font=dict(size=18),
        ),
        height=700,
        width=1400,
        paper_bgcolor="white",
        plot_bgcolor="white",
        margin=dict(l=70, r=30, t=110, b=80),
        font=dict(family="Arial, sans-serif", size=11),
    )

    # Grid styling for all axes
    fig.update_xaxes(
        showgrid=True,
        gridcolor="#e8e8e8",
        gridwidth=1,
        tickformat="%Y",
        tickangle=0,
        tickfont=dict(size=9),
        linecolor="#ccc",
        showline=True,
    )
    fig.update_yaxes(
        showgrid=True,
        gridcolor="#e8e8e8",
        gridwidth=1,
        tickfont=dict(size=9),
        linecolor="#ccc",
        showline=True,
        zeroline=False,
    )

    # Add % symbol to row-2 y-axes
    for col_idx in range(1, 5):
        fig.update_yaxes(ticksuffix="%", row=2, col=col_idx)

    # Source footnote
    fig.add_annotation(
        text="Source: Tesouro Nacional — Relatório Mensal da Dívida (RMD), Anexo 2.7",
        xref="paper",
        yref="paper",
        x=0,
        y=-0.08,
        showarrow=False,
        font=dict(size=10, color="#888"),
        xanchor="left",
    )

    return fig


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    df = fetch_data()
    fig = build_chart(df)

    os.makedirs(OUT_DIR, exist_ok=True)
    fig.write_html(OUT_FILE, include_plotlyjs="cdn")
    print(f"\nChart saved to: {os.path.abspath(OUT_FILE)}")


if __name__ == "__main__":
    main()
