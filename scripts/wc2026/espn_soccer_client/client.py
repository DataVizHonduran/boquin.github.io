"""ESPN hidden-API client for soccer player stats (no key required)."""
import urllib.request
import urllib.parse
import json

BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"
SEARCH = "https://site.web.api.espn.com/apis/search/v2"
OVERVIEW = "https://site.web.api.espn.com/apis/common/v3/sports/soccer"

# National-team confederation, keyed by ESPN's team displayName. Covers all
# 48 nations in the 2026 FIFA World Cup; extend as needed for other tournaments.
CONFEDERATION = {
    # CONCACAF
    "Mexico": "CONCACAF", "Canada": "CONCACAF", "United States": "CONCACAF",
    "Haiti": "CONCACAF", "Curaçao": "CONCACAF", "Panama": "CONCACAF",
    # CONMEBOL
    "Paraguay": "CONMEBOL", "Brazil": "CONMEBOL", "Uruguay": "CONMEBOL",
    "Argentina": "CONMEBOL", "Colombia": "CONMEBOL", "Ecuador": "CONMEBOL",
    # UEFA
    "Czechia": "UEFA", "Bosnia-Herzegovina": "UEFA", "Switzerland": "UEFA",
    "Scotland": "UEFA", "Türkiye": "UEFA", "Germany": "UEFA",
    "Netherlands": "UEFA", "Sweden": "UEFA", "Spain": "UEFA",
    "Belgium": "UEFA", "Norway": "UEFA", "Austria": "UEFA",
    "Portugal": "UEFA", "Croatia": "UEFA", "England": "UEFA", "France": "UEFA",
    # CAF
    "South Africa": "CAF", "Morocco": "CAF", "Ivory Coast": "CAF",
    "Tunisia": "CAF", "Egypt": "CAF", "Senegal": "CAF", "Algeria": "CAF",
    "Ghana": "CAF", "Congo DR": "CAF", "Cape Verde": "CAF",
    # AFC
    "South Korea": "AFC", "Qatar": "AFC", "Japan": "AFC",
    "Saudi Arabia": "AFC", "Iran": "AFC", "Iraq": "AFC", "Jordan": "AFC",
    "Uzbekistan": "AFC", "Australia": "AFC",
    # OFC
    "New Zealand": "OFC",
}

# FIFA Men's World Ranking position as of June 2026, keyed by ESPN displayName.
FIFA_RANKING = {
    "Argentina": 1, "Spain": 2, "France": 3, "England": 4, "Portugal": 5,
    "Brazil": 6, "Morocco": 7, "Netherlands": 8, "Belgium": 9, "Germany": 10,
    "Croatia": 11, "Colombia": 13, "Mexico": 14, "Senegal": 15, "Uruguay": 16,
    "United States": 17, "Japan": 18, "Switzerland": 19, "Iran": 20,
    "Türkiye": 22, "Ecuador": 23, "Austria": 24, "South Korea": 25,
    "Australia": 27, "Algeria": 28, "Egypt": 29, "Canada": 30, "Norway": 31,
    "Ivory Coast": 33, "Panama": 34, "Sweden": 38, "Czechia": 40,
    "Paraguay": 41, "Scotland": 42, "Tunisia": 45, "Congo DR": 46,
    "Uzbekistan": 50, "Qatar": 56, "Iraq": 57, "South Africa": 60,
    "Saudi Arabia": 61, "Jordan": 63, "Bosnia-Herzegovina": 64,
    "Cape Verde": 67, "Ghana": 73, "Curaçao": 82, "Haiti": 83,
    "New Zealand": 85,
}

CONFEDERATION_COLORS = {
    "UEFA": "#1f77b4", "CONMEBOL": "#d62728", "CONCACAF": "#2ca02c",
    "CAF": "#ff7f0e", "AFC": "#9467bd", "OFC": "#17becf",
    "Unknown": "#999999",
}


def _get(url):
    with urllib.request.urlopen(url) as r:
        return json.load(r)


class ESPNSoccerClient:
    def __init__(self, league="fifa.world"):
        self.league = league

    def search_player(self, name):
        """Returns list of {id, displayName, league, team} matches."""
        d = _get(f"{SEARCH}?query={urllib.parse.quote(name)}")
        for group in d.get("results", []):
            if group.get("type") == "player":
                out = []
                for c in group.get("contents", []):
                    out.append({
                        "id": c["link"]["web"].rstrip("/").split("/")[-2],
                        "name": c["displayName"],
                        "league": c.get("defaultLeagueSlug"),
                        "team": c.get("subtitle"),
                    })
                return out
        return []

    def player_overview(self, athlete_id):
        """Career splits by league/season for one player (counts, no minutes)."""
        return _get(f"{OVERVIEW}/{self.league}/athletes/{athlete_id}/overview")

    def scoreboard(self, date_range=None):
        """date_range: 'YYYYMMDD-YYYYMMDD' or None for today."""
        url = f"{BASE}/{self.league}/scoreboard"
        if date_range:
            url += f"?dates={date_range}"
        return _get(url)

    def completed_match_ids(self, date_range):
        """List of event ids with status Full Time within date_range."""
        d = self.scoreboard(date_range)
        ids = []
        for e in d.get("events", []):
            desc = e.get("status", {}).get("type", {}).get("description")
            if desc == "Full Time":
                ids.append(e["id"])
        return ids

    def match_summary(self, event_id):
        return _get(f"{BASE}/{self.league}/summary?event={event_id}")


def _stat(stats, name):
    for s in stats:
        if s["name"] == name:
            return s.get("value", 0)
    return 0


def _team_stat(stats, name):
    """Team boxscore stats carry no 'value' key, only a string 'displayValue'."""
    for s in stats:
        if s["name"] == name:
            return float(s.get("displayValue", 0) or 0)
    return 0.0


def _sub_minute_maps(summary):
    sub_in, sub_out = {}, {}
    for ev in summary.get("keyEvents", []):
        if ev.get("type", {}).get("type") != "substitution":
            continue
        try:
            part = ev["text"].split(". ", 1)[1]
            in_name, out_name = part.split(" replaces ")
            minute = ev["clock"]["value"] / 60.0
            sub_in[in_name.strip()] = minute
            sub_out[out_name.rstrip(".").strip()] = minute
        except Exception:
            continue
    return sub_in, sub_out


def aggregate_player_stats(client, event_ids, stat_names=("totalGoals", "totalShots", "shotsOnTarget")):
    """
    Walk every roster entry across the given matches and sum stats + minutes
    played per player. Minutes are derived from starter/subbedIn/subbedOut
    flags plus substitution-event clock times (normalized to a 90-min match).

    Returns: dict keyed by athlete id -> {name, team, matches, minutes, <stat_names...>}
    """
    players = {}
    for eid in event_ids:
        summary = client.match_summary(eid)
        sub_in, sub_out = _sub_minute_maps(summary)

        for team in summary.get("rosters", []):
            team_name = team["team"]["displayName"]
            for p in team.get("roster", []):
                ath = p["athlete"]
                name, pid = ath["displayName"], ath["id"]
                starter = p.get("starter", False)
                subbed_in = p.get("subbedIn", False)
                subbed_out = p.get("subbedOut", False)
                stats = p.get("stats", [])
                appearances = _stat(stats, "appearances")
                if appearances == 0 and not starter and not subbed_in:
                    continue

                if not subbed_in and not subbed_out:
                    minutes = 90.0
                elif not subbed_in and subbed_out:
                    minutes = sub_out.get(name, 90.0)
                elif subbed_in and not subbed_out:
                    minutes = 90.0 - sub_in.get(name, 0.0)
                else:
                    minutes = sub_out.get(name, 90.0) - sub_in.get(name, 0.0)

                rec = players.setdefault(pid, {
                    "name": name, "team": team_name,
                    "confederation": CONFEDERATION.get(team_name, "Unknown"),
                    "matches": 0, "minutes": 0.0,
                    **{s: 0 for s in stat_names}})
                rec["matches"] += 1
                rec["minutes"] += minutes
                for s in stat_names:
                    rec[s] += _stat(stats, s)
    return players


def aggregate_team_stats(client, event_ids,
                          stat_names=("totalShots", "possessionPct", "shotPct",
                                      "passPct", "longballPct",
                                      "totalCrosses", "accurateCrosses")):
    """
    Walk every team's boxscore across the given matches and average each
    stat per match played (percentage fields average cleanly; count fields
    become a per-match rate so teams with different match counts compare
    fairly).

    Returns: dict keyed by team display name -> {confederation, matches, <stat_names...>}
    """
    teams = {}
    for eid in event_ids:
        summary = client.match_summary(eid)
        for t in summary.get("boxscore", {}).get("teams", []):
            name = t["team"]["displayName"]
            rec = teams.setdefault(name, {
                "confederation": CONFEDERATION.get(name, "Unknown"),
                "rank": FIFA_RANKING.get(name, 100),
                "matches": 0, **{s: 0.0 for s in stat_names}})
            rec["matches"] += 1
            stats = t.get("statistics", [])
            for s in stat_names:
                rec[s] += _team_stat(stats, s)

    for rec in teams.values():
        m = rec["matches"]
        for s in stat_names:
            rec[s] = rec[s] / m if m else 0.0
    return teams
