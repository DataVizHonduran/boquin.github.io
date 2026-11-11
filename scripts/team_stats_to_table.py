"""Convert Rafa_City's public/team_stats.json (PS11, scraped daily behind the
ICN password gate) into a <th>-labelled HTML table chess_club_stats.py parses.

Usage: python3 team_stats_to_table.py <team_stats.json> <out.html>
"""
import html
import json
import sys

COLS = [("Name", "player_id"), ("Grade", "grade"), ("Chess Kid Rating", "ck_rating"),
        ("USCF Rating", "uscf_rating"), ("PLW", "mtd_plw"), ("PLW_YTD", "cumulative_plw")]

src, out = sys.argv[1], sys.argv[2]
d = json.load(open(src))
rows = ["<table><tr>" + "".join(f"<th>{h}</th>" for h, _ in COLS) + "</tr>"]
for p in d["players"]:
    rows.append("<tr>" + "".join(f"<td>{html.escape(str(p.get(k, '')))}</td>" for _, k in COLS) + "</tr>")
rows.append("</table>")
open(out, "w").write("".join(rows))
print(f"{len(d['players'])} players, generated_at {d.get('generated_at')}")
