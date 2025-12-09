"""
Generate index.html for CTA exhaustion signal charts
"""

import os
import json
from datetime import datetime

OUTPUT_DIR = "reports/cta-signals"

# Load summary data
with open(os.path.join(OUTPUT_DIR, 'summary.json'), 'r') as f:
    summary = json.load(f)

# Get list of chart files
chart_files = sorted([f for f in os.listdir(OUTPUT_DIR) if f.endswith('_exhaustion.html')])

# Extract currency names
currencies = [f.replace('_exhaustion.html', '') for f in chart_files]

# Sort latest positions
latest_positions = summary['latest_positions']
sorted_currencies = sorted(currencies, key=lambda x: latest_positions.get(x, 0), reverse=True)

html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CTA Exhaustion Signals</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            max-width: 1400px;
            margin: 0 auto;
            padding: 20px;
            background: #f5f5f5;
        }}
        h1 {{
            color: #333;
            border-bottom: 3px solid #007bff;
            padding-bottom: 10px;
        }}
        .info-box {{
            background: white;
            padding: 20px;
            border-radius: 8px;
            margin: 20px 0;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .info-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-top: 15px;
        }}
        .info-item {{
            padding: 10px;
            background: #f8f9fa;
            border-radius: 4px;
        }}
        .info-label {{
            font-weight: bold;
            color: #666;
            font-size: 0.9em;
        }}
        .info-value {{
            font-size: 1.2em;
            color: #333;
            margin-top: 5px;
        }}
        .currency-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
            gap: 15px;
            margin-top: 20px;
        }}
        .currency-card {{
            background: white;
            padding: 15px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            transition: transform 0.2s, box-shadow 0.2s;
            text-decoration: none;
            color: inherit;
            display: block;
        }}
        .currency-card:hover {{
            transform: translateY(-2px);
            box-shadow: 0 4px 8px rgba(0,0,0,0.15);
        }}
        .currency-name {{
            font-size: 1.3em;
            font-weight: bold;
            color: #007bff;
            margin-bottom: 10px;
        }}
        .position-info {{
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        .position-bar {{
            flex: 1;
            height: 20px;
            background: #e9ecef;
            border-radius: 4px;
            overflow: hidden;
            position: relative;
        }}
        .position-fill {{
            height: 100%;
            transition: width 0.3s;
        }}
        .position-long {{
            background: linear-gradient(90deg, #28a745, #20c997);
        }}
        .position-short {{
            background: linear-gradient(90deg, #dc3545, #e83e8c);
        }}
        .position-value {{
            font-weight: bold;
            min-width: 50px;
            text-align: right;
        }}
        .position-positive {{
            color: #28a745;
        }}
        .position-negative {{
            color: #dc3545;
        }}
        .last-updated {{
            color: #666;
            font-size: 0.9em;
            margin-top: 20px;
            text-align: center;
        }}
        .methodology {{
            background: #e7f3ff;
            padding: 15px;
            border-left: 4px solid #007bff;
            margin: 20px 0;
            border-radius: 4px;
        }}
        .methodology h3 {{
            margin-top: 0;
            color: #007bff;
        }}
    </style>
</head>
<body>
    <h1>📊 CTA Exhaustion Signals</h1>

    <div class="info-box">
        <div class="info-grid">
            <div class="info-item">
                <div class="info-label">CTA Model</div>
                <div class="info-value">{summary['cta_type'].upper()}</div>
            </div>
            <div class="info-item">
                <div class="info-label">EMA Windows</div>
                <div class="info-value">{summary['windows']}</div>
            </div>
            <div class="info-item">
                <div class="info-label">Currencies Tracked</div>
                <div class="info-value">{summary['currencies']}</div>
            </div>
            <div class="info-item">
                <div class="info-label">Last Updated</div>
                <div class="info-value">{datetime.fromisoformat(summary['generated_at']).strftime('%Y-%m-%d')}</div>
            </div>
        </div>
    </div>

    <div class="methodology">
        <h3>How It Works</h3>
        <p><strong>CTA Positioning:</strong> Measures momentum-following positioning using triple EMA convergence.
        Values range from -50 (max short) to +50 (max long).</p>
        <p><strong>Exhaustion Signals:</strong> Red markers indicate when extreme positioning unwinds,
        suggesting potential trend exhaustion and reversal opportunities.</p>
    </div>

    <h2>Currency Pairs</h2>
    <div class="currency-grid">
"""

for ccy in sorted_currencies:
    position = latest_positions.get(ccy, 0)
    position_abs = abs(position)
    position_pct = (position_abs / 50) * 100

    position_class = "position-positive" if position > 0 else "position-negative"
    bar_class = "position-long" if position > 0 else "position-short"

    # Position bar fills from center
    if position >= 0:
        bar_style = f"margin-left: 50%; width: {position_pct/2}%"
    else:
        bar_style = f"margin-left: {50 - position_pct/2}%; width: {position_pct/2}%"

    html_content += f"""
        <a href="{ccy}_exhaustion.html" class="currency-card">
            <div class="currency-name">{ccy}</div>
            <div class="position-info">
                <div class="position-bar">
                    <div class="position-fill {bar_class}" style="{bar_style}"></div>
                </div>
                <div class="position-value {position_class}">{position:.1f}</div>
            </div>
        </a>
"""

html_content += f"""
    </div>

    <div class="last-updated">
        Generated on {datetime.fromisoformat(summary['generated_at']).strftime('%Y-%m-%d %H:%M:%S UTC')}
    </div>

    <script>
        // Add keyboard navigation
        document.addEventListener('keydown', function(e) {{
            if (e.key === 'Escape') {{
                window.location.href = 'index.html';
            }}
        }});
    </script>
</body>
</html>
"""

# Write index.html
with open(os.path.join(OUTPUT_DIR, 'index.html'), 'w') as f:
    f.write(html_content)

print(f"✅ Generated index.html with {len(currencies)} currencies")
