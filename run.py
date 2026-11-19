#!/usr/bin/env python3
"""Free NFL bye-week & fantasy-playoff schedule grid. Python 3.8+, standard library only.

  python3 run.py grid [--roster "Josh Allen, Ja'Marr Chase, BUF DEF"] [--weeks 12-18]
  python3 run.py setkey            read your free BALLDONTLIE key from stdin and save it locally
  python3 run.py status            show where the key is read from and how fresh the cache is

The key comes from the BALLDONTLIE_API_KEY environment variable, or from the local config file written by
`setkey` (~/.config/dhsoft-fantasy-grids/config.json). It is only sent to api.balldontlie.io and never printed.
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
API = "https://api.balldontlie.io"
CONFIG = Path(os.environ.get("FANTASY_GRIDS_CONFIG") or Path.home() / ".config" / "dhsoft-fantasy-grids" / "config.json")
DATA = Path(os.environ.get("FREE_NFL_GRID_DATA") or HERE / "data")
SCHEDULE_MAX_AGE_H = 12
PLAYER_MAX_AGE_H = 24 * 7
MIN_INTERVAL_S = 12.5  # free plan: 5 requests per minute
PLAYOFF_WEEKS = (15, 16, 17)
LAST_WEEK = 18
FANTASY_POS = {"QB", "RB", "FB", "WR", "TE", "K", "PK"}

FOOTER = (
    "---\n"
    "Schedule data: BALLDONTLIE. Unofficial — not affiliated with, endorsed by, or sponsored by the NFL or any team. "
    "For season-long fantasy planning only; not betting or daily fantasy (DFS) contest advice.\n\n"
    "Want this checked automatically every 4 hours, with injuries, snap counts, start/sit and waiver picks? "
    "Try Fantasy NFL Roster Watch on Capafy (3-day free trial): "
    "https://capafy.ai/agent/fantasy-nfl-roster-watch-start-sit-waivers/2102998908"
)
KEY_HELP = (
    "Get a free BALLDONTLIE API key (about 1 minute): sign up at https://app.balldontlie.io and copy the key from "
    "your account page. Then either set the environment variable BALLDONTLIE_API_KEY, or run this yourself in a "
    "terminal and paste the key when asked: python3 run.py setkey"
)

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass


class Fail(Exception):
    """kind: api_key_missing, auth_failed, rate_limited, network, bad_response."""

    def __init__(self, kind: str, message: str, fix: str):
        super().__init__(message)
        self.kind, self.fix = kind, fix


# ---------- key and cache ----------

def load_key() -> tuple[str, str]:
    key = (os.environ.get("BALLDONTLIE_API_KEY") or "").strip()
    if key:
        return key, "environment variable BALLDONTLIE_API_KEY"
    try:
        key = (json.loads(CONFIG.read_text(encoding="utf-8")).get("balldontlie_api_key") or "").strip()
    except (OSError, ValueError):
        key = ""
    return key, (f"config file {CONFIG}" if key else "")


def save_key(key: str) -> None:
    key = key.strip()
    if not re.fullmatch(r"[A-Za-z0-9-]{16,100}", key):
        raise Fail("bad_key", "That does not look like a BALLDONTLIE API key.", KEY_HELP)
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    cfg = {}
    if CONFIG.exists():
        try:
            cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
        except ValueError:
            cfg = {}
    cfg["balldontlie_api_key"] = key
    CONFIG.write_text(json.dumps(cfg), encoding="utf-8")
    try:
        os.chmod(CONFIG, 0o600)
    except OSError:
        pass


def read_cache(name: str, max_age_h: float):
    p = DATA / name
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if time.time() - d.get("saved", 0) > max_age_h * 3600:
        return None
    return d.get("data")


def write_cache(name: str, data) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / name).write_text(json.dumps({"saved": time.time(), "data": data}), encoding="utf-8")


# ---------- HTTP (free plan: 5 requests per minute) ----------

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow redirects: urllib would copy the Authorization header (the key) to the new host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect())


def _urlopen(req, timeout):
    return _OPENER.open(req, timeout=timeout)


class Client:
    def __init__(self, key: str, sleep=None, min_interval: float = MIN_INTERVAL_S):
        self._key, self.min_interval = key, min_interval
        self._sleep = sleep or (lambda s: time.sleep(s))
        self._last = None
        self.requests = 0

    def get(self, path: str, params: list) -> dict:
        url = API + path + "?" + urllib.parse.urlencode(params)
        for attempt in range(3):
            if self._last is not None:
                gap = self.min_interval - (time.monotonic() - self._last)
                if gap > 0:
                    self._sleep(gap)
            self._last = time.monotonic()
            self.requests += 1
            req = urllib.request.Request(url, headers={"Authorization": self._key, "Accept": "application/json",
                                                       "User-Agent": "free-nfl-bye-grid/1.0"})
            try:
                with _urlopen(req, 15) as resp:
                    return json.load(resp)
            except urllib.error.HTTPError as exc:
                if exc.code in (401, 403):
                    raise Fail("auth_failed", "BALLDONTLIE rejected the API key (HTTP %d)." % exc.code,
                               "Check the key, or get a new free key. " + KEY_HELP)
                if exc.code == 429:
                    if attempt < 2:
                        print("Free plan limit reached (5 requests per minute); waiting 60 seconds...", file=sys.stderr)
                        self._sleep(61)
                        continue
                    raise Fail("rate_limited", "BALLDONTLIE's free plan limit (5 requests per minute) was "
                               "reached again.", "Wait a minute and run the command again.")
                if exc.code >= 500 and attempt < 2:
                    self._sleep(5)
                    continue
                raise Fail("network", "BALLDONTLIE returned HTTP %d." % exc.code, "Try again in a few minutes.")
            except ValueError:
                raise Fail("bad_response", "BALLDONTLIE sent a response that is not JSON.", "Try again in a few minutes.")
            except (urllib.error.URLError, OSError) as exc:
                if attempt < 2:
                    self._sleep(5)
                    continue
                raise Fail("network", "Could not reach api.balldontlie.io (%s)." % type(exc).__name__,
                           "Check your internet connection and try again.")
        raise Fail("network", "Could not reach api.balldontlie.io.", "Try again in a few minutes.")

    def paginate(self, path: str, params: list) -> list:
        items, cursor = [], None
        for _ in range(20):
            page = self.get(path, params + [("per_page", "100")] + ([("cursor", str(cursor))] if cursor else []))
            data = page.get("data")
            if not isinstance(data, list):
                raise Fail("bad_response", "Unexpected response from BALLDONTLIE (no data list).", "Try again later.")
            items += data
            cursor = (page.get("meta") or {}).get("next_cursor")
            if not cursor or not data:
                break
        return items


# ---------- data ----------

def clean(value) -> str:
    """Provider or user text printed into tables: drop characters that could break Markdown."""
    return "".join(" " if ch in "<>`|\r\n" else ch for ch in str(value or "")).strip()


def season_for(day: date) -> int:
    return day.year if day.month >= 3 else day.year - 1


def norm_game(g: dict) -> dict:
    state = (g.get("status_state") or "").lower()
    if not state:
        state = "final" if "final" in str(g.get("status") or "").lower() else "scheduled"
    return {"week": int(g.get("week") or 0), "post": bool(g.get("postseason")), "state": state,
            "home": clean(g["home_team"]["abbreviation"]), "away": clean(g["visitor_team"]["abbreviation"])}


def team_info(raw_games: list) -> dict:
    teams = {}
    for g in raw_games:
        for t in (g["home_team"], g["visitor_team"]):
            ab = clean(t["abbreviation"])
            teams[ab] = {"abbr": ab, "name": clean(t.get("name")), "full": clean(t.get("full_name"))}
    return teams


def load_schedule(client_factory, today: date) -> dict:
    season = season_for(today)
    cached = read_cache("schedule.json", SCHEDULE_MAX_AGE_H)
    if cached and cached.get("season") == season:
        return cached
    print("Downloading this season's schedule (3-4 requests on the free plan)...", file=sys.stderr)
    raw = client_factory().paginate("/nfl/v1/games", [("seasons[]", str(season))])
    sched = {"season": season, "fetched": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
             "games": [norm_game(g) for g in raw], "teams": team_info(raw)}
    if not sched["games"]:
        raise Fail("bad_response", "BALLDONTLIE returned no games for the %d season." % season, "Try again later.")
    write_cache("schedule.json", sched)
    return sched


def current_week(games: list) -> int:
    reg = [g for g in games if not g["post"] and g["week"]]
    open_weeks = [g["week"] for g in reg if g["state"] != "final"]
    return min(open_weeks) if open_weeks else max((g["week"] for g in reg), default=1)


def opponents(games: list) -> dict:
    """{team: {week: "KC" or "@KC"}} for the regular season."""
    out = {}
    for g in games:
        if g["post"] or not g["week"]:
            continue
        out.setdefault(g["home"], {})[g["week"]] = g["away"]
        out.setdefault(g["away"], {})[g["week"]] = "@" + g["home"]
    return out


# ---------- names ----------

def norm_name(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9/ ]", " ", s)
    return " ".join(w for w in s.split() if w not in {"jr", "sr", "ii", "iii", "iv", "v"})


def defense_team(raw: str, teams: dict):
    """'BUF DEF', 'Bills D/ST', 'Buffalo Bills defense' -> 'BUF'."""
    n = norm_name(raw)
    m = re.fullmatch(r"(.+?) (def|defense|dst|d/st|d st|d)", n)
    if not m:
        return None
    base = m.group(1)
    for ab, t in teams.items():
        if base in (ab.lower(), norm_name(t["name"]), norm_name(t["full"])):
            return ab
    return None


def lookup_player(client_factory, raw: str) -> list:
    """Candidates from BALLDONTLIE's player search (cached a week per search word)."""
    words = norm_name(raw).split()
    if not words:
        return []
    # A misspelled last name finds nothing, so fall back to the first name, then the first letters of the last name.
    for term in dict.fromkeys([words[-1], words[0], words[-1][:4]]):
        if len(term) >= 3:
            found = _search(client_factory, term)
            if found:
                return found
    return []


def _search(client_factory, term: str) -> list:
    cache = read_cache("players.json", PLAYER_MAX_AGE_H * 10) or {}
    hit = cache.get(term)
    if hit is None or time.time() - hit.get("at", 0) > PLAYER_MAX_AGE_H * 3600:
        found = client_factory().paginate("/nfl/v1/players", [("search", term)])
        hit = {"at": time.time(), "players": [
            {"name": clean("%s %s" % (p.get("first_name", ""), p.get("last_name", ""))),
             "pos": (p.get("position_abbreviation") or "").upper(),
             "team": clean((p.get("team") or {}).get("abbreviation"))} for p in found]}
        cache[term] = hit
        write_cache("players.json", cache)
    return hit["players"]


def match_roster(client_factory, names: list, teams: dict) -> tuple[list, list, list]:
    """Returns (players [{name,pos,team}], unmatched names, notes about corrected spellings)."""
    out, unmatched, notes = [], [], []
    for raw in names:
        raw = raw.strip()
        if not raw:
            continue
        ab = defense_team(raw, teams)
        if ab:
            out.append({"name": "%s D/ST" % ab, "pos": "DEF", "team": ab})
            continue
        cands = [c for c in lookup_player(client_factory, raw) if c["team"] and c["pos"] in FANTASY_POS]
        pool = {}
        for c in cands:
            pool.setdefault(norm_name(c["name"]), []).append(c)
        key = norm_name(raw)
        hit = pool.get(key)
        if not hit:
            close = difflib.get_close_matches(key, list(pool), n=1, cutoff=0.8)
            if close:
                hit = pool[close[0]]
                notes.append("'%s' matched to %s" % (clean(raw), hit[0]["name"]))
        if hit:
            p = dict(hit[0])
            p["pos"] = {"PK": "K", "FB": "RB"}.get(p["pos"], p["pos"])
            if p not in out:  # the same player typed twice counts once
                out.append(p)
        else:
            unmatched.append(clean(raw))
    return out, unmatched, notes


# ---------- report ----------

def parse_weeks(spec, cw: int) -> list:
    if not spec:
        return list(range(cw, LAST_WEEK + 1))
    m = re.fullmatch(r"\s*(\d{1,2})\s*(?:-\s*(\d{1,2}))?\s*", spec)
    if not m:
        raise Fail("bad_weeks", "Weeks must look like 12-18 or 15.", 'Example: --weeks 15-17')
    a, b = int(m.group(1)), int(m.group(2) or m.group(1))
    if not 1 <= a <= b <= LAST_WEEK:
        raise Fail("bad_weeks", "Weeks must be between 1 and %d." % LAST_WEEK, 'Example: --weeks 15-17')
    return list(range(a, b + 1))


def wk_label(w: int) -> str:
    return "W%d%s" % (w, "*" if w in PLAYOFF_WEEKS else "")


def cell(opp: dict, w: int) -> str:
    return opp.get(w, "**BYE**")


def report(sched: dict, weeks: list, roster=None, unmatched=(), notes=()) -> str:
    opp = opponents(sched["games"])
    cw = current_week(sched["games"])
    L = ["# NFL bye weeks & fantasy playoff schedule — weeks %d-%d (%d season)" % (weeks[0], weeks[-1], sched["season"]),
         "",
         "Current week: %d. Schedule updated %s. `*` = usual fantasy playoff weeks (15-17)." % (cw, sched["fetched"]),
         ""]
    for n in notes:
        L.append("- Spelling corrected: %s" % n)
    if notes:
        L.append("")
    if roster is not None:
        L += ["## Your roster", "", "| Player | Pos | Team | " + " | ".join(wk_label(w) for w in weeks) + " |",
              "|---|---|---|" + "---|" * len(weeks)]
        for p in roster:
            row = opp.get(p["team"], {})
            L.append("| %s | %s | %s | %s |" % (p["name"], p["pos"], p["team"], " | ".join(cell(row, w) for w in weeks)))
        if unmatched:
            L += ["", "Not found (check the spelling, or add the team, e.g. \"BUF DEF\"): %s" % ", ".join(unmatched)]
        L += ["", "## Weeks your roster is short", ""]
        short = shortages(roster, opp, weeks)
        L += short or ["- No week in this range has a bye problem for your roster."]
        L.append("")
    L += ["## Teams on bye", ""]
    for w in weeks:
        on_bye = sorted(t for t in opp if w not in opp[t])
        L.append("- %s: %s" % (wk_label(w), ", ".join(on_bye) if on_bye else "none"))
    L += ["", "## Every team's opponents", "", "| Team | " + " | ".join(wk_label(w) for w in weeks) + " |",
          "|---|" + "---|" * len(weeks)]
    for t in sorted(opp):
        L.append("| %s | %s |" % (t, " | ".join(cell(opp[t], w) for w in weeks)))
    L += ["", FOOTER]
    return "\n".join(L)


def shortages(roster: list, opp: dict, weeks: list) -> list:
    """Per week: positions where every rostered player is on bye, or where two or more are on bye."""
    out = []
    by_pos = {}
    for p in roster:
        by_pos.setdefault(p["pos"], []).append(p)
    for w in weeks:
        parts = []
        for pos in ("QB", "RB", "WR", "TE", "K", "DEF"):
            ps = by_pos.get(pos, [])
            gone = [p["name"] for p in ps if w not in opp.get(p["team"], {})]
            if not gone:
                continue
            if len(gone) == len(ps):
                parts.append("no %s available (%s on bye)" % (pos, ", ".join(gone)))
            elif len(gone) >= 2:
                parts.append("%d %s on bye (%s)" % (len(gone), pos, ", ".join(gone)))
        if parts:
            out.append("- %s: %s" % (wk_label(w), "; ".join(parts)))
    return out


# ---------- commands ----------

def make_client_factory():
    holder = {}

    def factory():
        if "c" not in holder:
            key, _ = load_key()
            if not key:
                raise Fail("api_key_missing", "No BALLDONTLIE API key is set up yet.", KEY_HELP)
            holder["c"] = Client(key)
        return holder["c"]
    return factory


def cmd_grid(a) -> None:
    factory = make_client_factory()
    sched = load_schedule(factory, date.today())
    weeks = parse_weeks(a.weeks, current_week(sched["games"]))
    roster = unmatched = notes = None
    if a.roster:
        names = [n for n in a.roster.replace("\n", ",").split(",") if n.strip()][:40]
        if len(names) > 1:
            print("Looking up %d names (up to %d seconds on the free plan; names looked up before are cached)..."
                  % (len(names), int(len(names) * MIN_INTERVAL_S)), file=sys.stderr)
        roster, unmatched, notes = match_roster(factory, names, sched["teams"])
    print(report(sched, weeks, roster, unmatched or (), notes or ()))


def cmd_setkey(a) -> None:
    if sys.stdin.isatty():
        import getpass
        key = getpass.getpass("Paste your BALLDONTLIE API key (input hidden): ")
    else:
        key = sys.stdin.readline()
    save_key(key)
    print("KEY SAVED to %s (only this computer; it is sent only to api.balldontlie.io)." % CONFIG)


def cmd_status(a) -> None:
    key, src = load_key()
    print("API key: %s" % ("set (%s)" % src if key else "not set. " + KEY_HELP))
    sched = read_cache("schedule.json", 10 ** 6)
    print("Schedule cache: %s" % (sched["fetched"] if sched else "none yet"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Free NFL bye-week & fantasy playoff schedule grid")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("grid")
    p.add_argument("--roster", help='comma-separated names, e.g. "Josh Allen, Ja\'Marr Chase, BUF DEF"')
    p.add_argument("--weeks", help="range such as 12-18 (default: current week to 18)")
    sub.add_parser("setkey")
    sub.add_parser("status")
    a = ap.parse_args(argv)
    try:
        {"grid": cmd_grid, "setkey": cmd_setkey, "status": cmd_status}[a.cmd](a)
    except Fail as exc:
        print("ERROR [%s]: %s" % (exc.kind, exc), file=sys.stderr)
        print("HOW TO FIX: %s" % exc.fix, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
