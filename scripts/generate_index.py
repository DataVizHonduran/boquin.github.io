"""
Generate index.html with bar chart landing page and mode selector
"""

import os
import json
from datetime import datetime
import plotly.graph_objects as go
import plotly.io as pio

OUTPUT_DIR = "reports/cta-signals"

# Load summary data
with open(os.path.join(OUTPUT_DIR, 'summary.json'), 'r') as f:
    all_summaries = json.load(f)

# Get positions for both modes
fast_positions = all_summaries['fast']['latest_positions']
slow_positions = all_summaries['slow']['latest_positions']

# Create bar charts for both modes
def create_position_bar_chart(positions, mode):
    """Create interactive bar chart of current positions"""
    # Sort currencies by position for THIS mode (most long to most short)
    sorted_currencies = sorted(positions.keys(), key=lambda x: positions[x], reverse=True)
    currencies = sorted_currencies
    values = [positions[ccy] for ccy in currencies]

    # Color bars based on position
    colors = ['#28a745' if v > 0 else '#dc3545' for v in values]

    fig = go.Figure()

    fig.add_trace(go.Bar(
        x=currencies,
        y=values,
        marker=dict(
            color=colors,
            line=dict(color='rgba(0,0,0,0.3)', width=1)
        ),
        hovertemplate='<b>%{x}</b><br>Position: %{y:.1f}<extra></extra>',
        customdata=currencies
    ))

    fig.update_layout(
        title=dict(
            text=f"CTA {mode.upper()} Mode - Current Positioning",
            x=0.5,
            xanchor='center',
            font=dict(size=22, color='#333')
        ),
        xaxis=dict(
            title="Currency",
            showgrid=False,
            tickangle=-45,
            tickfont=dict(size=11)
        ),
        yaxis=dict(
            title="Position Size",
            showgrid=True,
            gridcolor='#e9ecef',
            zeroline=True,
            zerolinecolor='#333',
            zerolinewidth=2,
            range=[-55, 55]
        ),
        plot_bgcolor='white',
        height=500,
        margin=dict(b=100),
        hovermode='closest'
    )

    return fig

# Generate both charts
fast_fig = create_position_bar_chart(fast_positions, 'fast')
slow_fig = create_position_bar_chart(slow_positions, 'slow')

# Save as HTML divs (not full pages)
fast_html = pio.to_html(fast_fig, include_plotlyjs=False, div_id='fast-chart')
slow_html = pio.to_html(slow_fig, include_plotlyjs=False, div_id='slow-chart')

# Create full HTML page
html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CTA Exhaustion Signals</title>
    <script src="https://cdn.plot.ly/plotly-2.26.0.min.js"></script>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: #f5f5f5;
            padding: 20px;
        }}

        .container {{
            max-width: 1400px;
            margin: 0 auto;
        }}

        h1 {{
            color: #333;
            border-bottom: 3px solid #007bff;
            padding-bottom: 15px;
            margin-bottom: 20px;
        }}

        .info-box {{
            background: white;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}

        .methodology {{
            background: #e7f3ff;
            padding: 15px;
            border-left: 4px solid #007bff;
            margin-bottom: 20px;
            border-radius: 4px;
        }}

        .methodology h3 {{
            margin: 0 0 10px 0;
            color: #007bff;
        }}

        .methodology p {{
            margin: 5px 0;
            line-height: 1.6;
        }}

        .mode-selector {{
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
            justify-content: center;
        }}

        .mode-btn {{
            padding: 12px 30px;
            font-size: 16px;
            font-weight: bold;
            border: 2px solid #007bff;
            background: white;
            color: #007bff;
            border-radius: 6px;
            cursor: pointer;
            transition: all 0.3s;
        }}

        .mode-btn:hover {{
            background: #e7f3ff;
        }}

        .mode-btn.active {{
            background: #007bff;
            color: white;
        }}

        .chart-container {{
            background: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            margin-bottom: 20px;
        }}

        .chart-wrapper {{
            display: none;
        }}

        .chart-wrapper.active {{
            display: block;
        }}

        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-top: 15px;
        }}

        .stat-item {{
            padding: 15px;
            background: #f8f9fa;
            border-radius: 6px;
            text-align: center;
        }}

        .stat-label {{
            font-size: 0.9em;
            color: #666;
            margin-bottom: 5px;
        }}

        .stat-value {{
            font-size: 1.5em;
            font-weight: bold;
            color: #333;
        }}

        .last-updated {{
            text-align: center;
            color: #666;
            font-size: 0.9em;
            margin-top: 20px;
        }}

        .currency-list {{
            margin-top: 20px;
        }}

        .currency-list h3 {{
            margin-bottom: 15px;
            color: #333;
        }}

        .currency-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
            gap: 10px;
        }}

        .currency-link {{
            display: block;
            padding: 10px;
            background: white;
            border: 1px solid #dee2e6;
            border-radius: 4px;
            text-decoration: none;
            color: #007bff;
            font-weight: 500;
            transition: all 0.2s;
            text-align: center;
        }}

        .currency-link:hover {{
            background: #e7f3ff;
            border-color: #007bff;
            transform: translateY(-2px);
            box-shadow: 0 2px 4px rgba(0,123,255,0.2);
        }}

        .position-badge {{
            display: inline-block;
            margin-left: 8px;
            padding: 2px 8px;
            border-radius: 3px;
            font-size: 0.85em;
            font-weight: bold;
        }}

        .position-long {{
            background: #d4edda;
            color: #155724;
        }}

        .position-short {{
            background: #f8d7da;
            color: #721c24;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 CTA Exhaustion Signals</h1>

        <div class="info-box">
            <div class="stats-grid">
                <div class="stat-item">
                    <div class="stat-label">Currencies Tracked</div>
                    <div class="stat-value">{all_summaries['fast']['currencies']}</div>
                </div>
                <div class="stat-item">
                    <div class="stat-label">Fast Mode Windows</div>
                    <div class="stat-value">{all_summaries['fast']['windows']}</div>
                </div>
                <div class="stat-item">
                    <div class="stat-label">Slow Mode Windows</div>
                    <div class="stat-value">{all_summaries['slow']['windows']}</div>
                </div>
                <div class="stat-item">
                    <div class="stat-label">Last Updated</div>
                    <div class="stat-value">{datetime.fromisoformat(all_summaries['fast']['generated_at']).strftime('%Y-%m-%d')}</div>
                </div>
            </div>
        </div>

        <div class="methodology">
            <h3>How It Works</h3>
            <p><strong>CTA Positioning:</strong> Measures momentum-following positioning using triple EMA convergence.
            Values range from -50 (max short) to +50 (max long).</p>
            <p><strong>Fast Mode:</strong> Uses 20/50/100 day EMAs for more responsive signals.</p>
            <p><strong>Slow Mode:</strong> Uses 50/100/200 day EMAs for longer-term trends.</p>
            <p><strong>Exhaustion Signals:</strong> Red markers on charts indicate when extreme positioning unwinds,
            suggesting potential trend exhaustion and reversal opportunities.</p>
        </div>

        <div class="mode-selector">
            <button class="mode-btn active" onclick="showMode('fast')">FAST Mode (20/50/100)</button>
            <button class="mode-btn" onclick="showMode('slow')">SLOW Mode (50/100/200)</button>
        </div>

        <div class="chart-container">
            <div id="fast-chart-wrapper" class="chart-wrapper active">
                {fast_html}
            </div>
            <div id="slow-chart-wrapper" class="chart-wrapper">
                {slow_html}
            </div>
        </div>

        <div class="currency-list">
            <h3>View Individual Currency Charts</h3>
            <div class="currency-grid" id="currency-grid">
            </div>
        </div>

        <div class="last-updated">
            Last updated: {datetime.fromisoformat(all_summaries['fast']['generated_at']).strftime('%Y-%m-%d %H:%M UTC')}
        </div>
    </div>

    <script>
        let currentMode = 'fast';

        const fastPositions = {json.dumps(fast_positions)};
        const slowPositions = {json.dumps(slow_positions)};

        function getSortedCurrencies(positions) {{
            // Sort currencies by position (most long to most short)
            return Object.keys(positions).sort((a, b) => positions[b] - positions[a]);
        }}

        function showMode(mode) {{
            currentMode = mode;

            // Update buttons
            document.querySelectorAll('.mode-btn').forEach(btn => {{
                btn.classList.remove('active');
            }});
            event.target.classList.add('active');

            // Update charts
            document.querySelectorAll('.chart-wrapper').forEach(wrapper => {{
                wrapper.classList.remove('active');
            }});
            const activeWrapper = document.getElementById(mode + '-chart-wrapper');
            activeWrapper.classList.add('active');

            // Force Plotly to resize the chart after it becomes visible
            setTimeout(() => {{
                const chartDiv = activeWrapper.querySelector('[id$="-chart"]');
                if (chartDiv && window.Plotly) {{
                    window.Plotly.Plots.resize(chartDiv);
                }}
            }}, 50);

            // Update currency links
            updateCurrencyGrid();
        }}

        function updateCurrencyGrid() {{
            const positions = currentMode === 'fast' ? fastPositions : slowPositions;
            const sortedCurrencies = getSortedCurrencies(positions);
            const grid = document.getElementById('currency-grid');

            grid.innerHTML = sortedCurrencies.map(ccy => {{
                const pos = positions[ccy];
                const badge = pos > 0
                    ? `<span class="position-badge position-long">+${{pos.toFixed(1)}}</span>`
                    : `<span class="position-badge position-short">${{pos.toFixed(1)}}</span>`;

                return `<a href="${{ccy}}_exhaustion_${{currentMode}}.html" class="currency-link">
                    ${{ccy}}${{badge}}
                </a>`;
            }}).join('');
        }}

        // Add click handler to bars
        document.addEventListener('DOMContentLoaded', function() {{
            updateCurrencyGrid();

            // Add click handlers to Plotly charts
            const charts = document.querySelectorAll('[id$="-chart"]');
            charts.forEach(chart => {{
                chart.on('plotly_click', function(data) {{
                    const ccy = data.points[0].x;
                    window.location.href = `${{ccy}}_exhaustion_${{currentMode}}.html`;
                }});
            }});
        }});
    </script>
</body>
</html>
"""

# Write index.html
with open(os.path.join(OUTPUT_DIR, 'index.html'), 'w') as f:
    f.write(html_content)

print(f"✅ Generated index.html with bar charts for {len(fast_positions)} currencies")
print(f"   - FAST mode chart with {all_summaries['fast']['windows']} windows")
print(f"   - SLOW mode chart with {all_summaries['slow']['windows']} windows")
