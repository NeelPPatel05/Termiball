#!/usr/bin/env python3
"""
NBA Live Auto-Tracker
Box score + play feed via ESPN summary endpoint.
"""

import curses, subprocess, json, time, threading
from datetime import datetime

ESPN_SCORE_URL   = "http://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
ESPN_SUMMARY_URL = "http://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={eid}"
REFRESH_SEC      = 15

LOCK = threading.Lock()
LIVE = {
    "home_name": "",  "away_name": "",
    "home_abbr": "",  "away_abbr": "",
    "home_score": 0,  "away_score": 0,
    "home_qs": [],    "away_qs": [],
    "home_players": [], "away_players": [],
    "home_team_stats": {}, "away_team_stats": {},
    "plays": [],
    "period": 0, "clock": "--:--",
    "status": "Scheduled", "status_type": "scheduled",
    "game_title": "", "game_detail": "",
    "updated": "Never", "error": None,
}

# curses color pair indices
C_HEADER=1; C_HOME=2; C_AWAY=3; C_WARN=4; C_NORMAL=5; C_DIM=6; C_LIVE=7

# terminal color slot indices for team colors (above the 8 standard colors)
HOME_COLOR_IDX = 10
AWAY_COLOR_IDX = 11

def init_colors():
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(C_HEADER, curses.COLOR_BLACK, curses.COLOR_WHITE)
    curses.init_pair(C_HOME,   curses.COLOR_CYAN,    -1)
    curses.init_pair(C_AWAY,   curses.COLOR_MAGENTA, -1)
    curses.init_pair(C_WARN,   curses.COLOR_RED,     -1)
    curses.init_pair(C_NORMAL, curses.COLOR_WHITE,   -1)
    curses.init_pair(C_DIM,    8,                    -1)
    curses.init_pair(C_LIVE,   curses.COLOR_GREEN,   -1)

# safe addstr — silently clips or skips draws outside the window boundary
def sadd(win, y, x, text, attr=0):
    h, w = win.getmaxyx()
    if y < 0 or y >= h or x < 0: return
    text = str(text)
    avail = w - x - 1
    if avail <= 0: return
    try: win.addstr(y, x, text[:avail], attr)
    except curses.error: pass

def hl(win, y):
    h, w = win.getmaxyx()
    if 0 <= y < h:
        try: win.hline(y, 0, curses.ACS_HLINE, w - 1)
        except curses.error: pass

def _parse_hex(hex_str):
    h = hex_str.lstrip("#")
    if len(h) != 6: return None
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)

def hex_brightness(hex_str):
    rgb = _parse_hex(hex_str)
    if not rgb: return 0
    r, g, b = rgb
    # ITU-R 601 luma — perceptual brightness, not a simple average
    return (r * 299 + g * 587 + b * 114) // 1000

def hex_to_curses_rgb(hex_str):
    rgb = _parse_hex(hex_str)
    if not rgb: return None
    r, g, b = rgb
    # curses expects 0–1000 range, not 0–255
    return (r * 1000 // 255, g * 1000 // 255, b * 1000 // 255)

def pick_team_color(primary, alt):
    # fall back to alternate when primary is too dark to read on a black terminal
    if hex_brightness(primary) < 50 and alt:
        return alt
    return primary

def set_team_colors(home_hex, home_alt, away_hex, away_alt):
    # can_change_color requires a terminal that supports color mutation (e.g. xterm-256color)
    if not curses.can_change_color() or curses.COLORS < 16:
        return
    home_rgb = hex_to_curses_rgb(pick_team_color(home_hex, home_alt)) if home_hex else None
    away_rgb = hex_to_curses_rgb(pick_team_color(away_hex, away_alt)) if away_hex else None
    if home_rgb:
        curses.init_color(HOME_COLOR_IDX, *home_rgb)
        curses.init_pair(C_HOME, HOME_COLOR_IDX, -1)
    if away_rgb:
        curses.init_color(AWAY_COLOR_IDX, *away_rgb)
        curses.init_pair(C_AWAY, AWAY_COLOR_IDX, -1)

def curl_get(url):
    r = subprocess.run(["curl", "-s", "--max-time", "10", url], capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        raise RuntimeError(f"curl failed rc={r.returncode}")
    return json.loads(r.stdout)

# ESPN stat label → short display key
LABEL_MAP = {
    "MIN":"min","PTS":"pts","FG":"fg","3PT":"3p","FT":"ft",
    "REB":"reb","AST":"ast","TO":"to","STL":"stl","BLK":"blk","PF":"pf","+/-":"pm",
}

def parse_players(team_box):
    players = []
    for block in team_box.get("statistics", []):
        labels = block.get("names", [])
        for entry in block.get("athletes", []):
            if entry.get("didNotPlay", False):
                continue
            has_stats = any(v not in ("0","-","0-0","0:00","") for v in entry.get("stats",[]))
            if not has_stats:
                continue
            athlete = entry.get("athlete", {})
            vals    = entry.get("stats", [])
            stat    = {LABEL_MAP.get(lbl, lbl.lower()): val for lbl, val in zip(labels, vals)}
            pos_raw = athlete.get("position", {})
            pos     = pos_raw.get("abbreviation", "-") if isinstance(pos_raw, dict) else str(pos_raw)
            players.append({
                "name":     athlete.get("displayName", "?"),
                "pos":      pos,
                "starter":  entry.get("starter", False),
                "on_court": entry.get("active", False),
                **{k: stat.get(k, "-") for k in ["min","pts","reb","ast","stl","blk","to","fg","3p","ft","pf","pm"]},
            })
    # starters first, then sorted by points descending within each group
    players.sort(key=lambda p: (not p["starter"], -(int(p["pts"]) if str(p["pts"]).lstrip("-").isdigit() else 0)))
    return players

def parse_team_stats(summary, home_abbr):
    hts, ats = {}, {}
    for team in summary.get("boxscore", {}).get("teams", []):
        abbr  = team.get("team", {}).get("abbreviation", "")
        stats = {s["name"]: s.get("displayValue", "-") for s in team.get("statistics", [])}
        if abbr == home_abbr: hts = stats
        else: ats = stats
    return hts, ats

def parse_plays(summary):
    plays = []
    for play in summary.get("plays", [])[-40:]:
        text = play.get("text", "").strip()
        if not text: continue
        period = play.get("period", {}).get("number", "")
        clock  = play.get("clock", {}).get("displayValue", "")
        hs     = play.get("homeScore", "")
        as_    = play.get("awayScore", "")
        # ESPN returns away/home separately; combine as "away-home" to match scoreboard convention
        score  = f" [{as_}-{hs}]" if hs != "" else ""
        qlbl   = f"Q{period} {clock}" if period else ""
        plays.append(f"{qlbl:<11}{text}{score}")
    plays.reverse()  # newest first
    return plays

def fetch_games():
    data  = curl_get(ESPN_SCORE_URL)
    games = []
    for e in data.get("events", []):
        c           = e["competitions"][0]
        competitors = c["competitors"]
        home = next((t for t in competitors if t["homeAway"] == "home"), competitors[0])
        away = next((t for t in competitors if t["homeAway"] == "away"), competitors[1])
        st   = e["status"]
        games.append({
            "id":         e["id"],
            "name":       e.get("name", ""),
            "home_name":  home["team"]["displayName"],
            "away_name":  away["team"]["displayName"],
            "home_abbr":  home["team"]["abbreviation"],
            "away_abbr":  away["team"]["abbreviation"],
            "home_score": home.get("score", ""),
            "away_score": away.get("score", ""),
            "home_color":     home["team"].get("color", ""),
            "home_alt_color": home["team"].get("alternateColor", ""),
            "away_color":     away["team"].get("color", ""),
            "away_alt_color": away["team"].get("alternateColor", ""),
            "status_type": st["type"]["name"],
            "detail":     st["type"].get("shortDetail", st["type"]["description"]),
        })
    return games

def _exit_msg(scr, msg):
    h, _ = scr.getmaxyx()
    scr.erase()
    sadd(scr, h // 2,     2, msg,                    curses.color_pair(C_WARN))
    sadd(scr, h // 2 + 1, 2, "Press any key to exit.", curses.color_pair(C_DIM))
    scr.refresh()
    scr.getch()

def pick_game(scr):
    init_colors()
    curses.curs_set(0)
    curses.noecho()
    scr.nodelay(False)

    h, w = scr.getmaxyx()
    loading = "Fetching today's games..."
    scr.clear()
    sadd(scr, h // 2, (w - len(loading)) // 2, loading, curses.color_pair(C_DIM))
    scr.refresh()

    try:
        games = fetch_games()
    except Exception as e:
        _exit_msg(scr, f"Error fetching schedule: {e}")
        return None

    if not games:
        _exit_msg(scr, "No NBA games scheduled today.")
        return None

    sel = 0
    while True:
        scr.erase()
        h, w = scr.getmaxyx()
        hdr = " NBA LIVE TRACKER  |  Select a Game "
        sadd(scr, 0, 0, hdr.center(w), curses.color_pair(C_HEADER) | curses.A_BOLD)
        sadd(scr, 2, 2, "UP/DOWN or J/K to move  |  ENTER to select  |  Q to quit",
             curses.color_pair(C_DIM))
        hl(scr, 3)

        for i, g in enumerate(games):
            row = 4 + i * 2
            if row >= h - 2:
                break
            stype = g["status_type"]
            if "in" in stype:
                status_label = f"LIVE  {g['away_score']}-{g['home_score']}"
                status_color = C_LIVE
            elif "post" in stype:
                status_label = f"FINAL  {g['away_score']}-{g['home_score']}"
                status_color = C_DIM
            else:
                status_label = g["detail"]
                status_color = C_NORMAL

            matchup = f"{g['away_name']}  @  {g['home_name']}"
            if i == sel:
                sadd(scr, row, 2, ">", curses.color_pair(C_HEADER) | curses.A_BOLD)
                sadd(scr, row, 4, matchup, curses.color_pair(C_HEADER) | curses.A_BOLD)
            else:
                sadd(scr, row, 4, matchup, curses.color_pair(C_NORMAL))
            sadd(scr, row, 4 + len(matchup) + 3, status_label,
                 curses.color_pair(status_color) | (curses.A_BOLD if "in" in stype else 0))

        scr.refresh()
        key = scr.getch()
        if key in (curses.KEY_UP, ord("k")) and sel > 0:
            sel -= 1
        elif key in (curses.KEY_DOWN, ord("j")) and sel < len(games) - 1:
            sel += 1
        elif key in (curses.KEY_ENTER, 10, 13):
            return games[sel]
        elif key in (ord("q"), ord("Q")):
            return None

def poll(event_id):
    # runs in a daemon thread; writes to LIVE under LOCK every REFRESH_SEC seconds
    while True:
        try:
            data        = curl_get(ESPN_SCORE_URL)
            event, comp = None, None
            for e in data.get("events", []):
                if e["id"] == event_id:
                    event, comp = e, e["competitions"][0]
                    break

            if event is None:
                with LOCK:
                    LIVE["error"]   = "Game not found in today's schedule."
                    LIVE["updated"] = datetime.now().strftime("%H:%M:%S")
                time.sleep(REFRESH_SEC)
                continue

            summary = curl_get(ESPN_SUMMARY_URL.format(eid=event_id))

            with LOCK:
                LIVE["error"]       = None
                LIVE["updated"]     = datetime.now().strftime("%H:%M:%S")
                st = event["status"]
                LIVE["status_type"] = st["type"]["name"]
                LIVE["status"]      = st["type"]["description"]
                LIVE["period"]      = st.get("period", 0)
                LIVE["clock"]       = st.get("displayClock", "--:--")
                LIVE["game_detail"] = st["type"].get("shortDetail", "")
                LIVE["game_title"]  = event.get("name", "")

                competitors = comp["competitors"]
                home = next(c for c in competitors if c["homeAway"] == "home")
                away = next(c for c in competitors if c["homeAway"] == "away")
                LIVE["home_name"]  = home["team"]["displayName"]
                LIVE["away_name"]  = away["team"]["displayName"]
                LIVE["home_abbr"]  = home["team"]["abbreviation"]
                LIVE["away_abbr"]  = away["team"]["abbreviation"]
                LIVE["home_score"] = int(home.get("score") or 0)
                LIVE["away_score"] = int(away.get("score") or 0)
                LIVE["home_qs"]    = [int(l["value"]) for l in home.get("linescores", [])]
                LIVE["away_qs"]    = [int(l["value"]) for l in away.get("linescores", [])]

                for team_box in summary.get("boxscore", {}).get("players", []):
                    abbr   = team_box.get("team", {}).get("abbreviation", "")
                    parsed = parse_players(team_box)
                    if abbr == LIVE["home_abbr"]: LIVE["home_players"] = parsed
                    else: LIVE["away_players"] = parsed

                hts, ats = parse_team_stats(summary, LIVE["home_abbr"])
                LIVE["home_team_stats"] = hts
                LIVE["away_team_stats"] = ats
                LIVE["plays"]           = parse_plays(summary)

        except Exception as e:
            with LOCK:
                LIVE["error"]   = str(e)[:80]
                LIVE["updated"] = datetime.now().strftime("%H:%M:%S")
        time.sleep(REFRESH_SEC)

# header label, player dict key, column width
COLS = [
    ("NAME", "name", 20), ("POS", "pos", 3),  ("MIN", "min", 5), ("PTS", "pts", 4),
    ("REB",  "reb",  4),  ("AST", "ast", 4),  ("STL", "stl", 4), ("BLK", "blk", 4),
    ("TO",   "to",   3),  ("FG",  "fg",  6),  ("3PT", "3p",  5), ("FT",  "ft",  5),
    ("PF",   "pf",   3),  ("+/-", "pm",  4),
]

def fmt_row(p, header=False):
    parts = []
    for hdr, key, w in COLS:
        val = hdr if header else str(p.get(key, "-"))
        parts.append(val[:w].ljust(w) if key == "name" else val[:w].rjust(w))
    return "  ".join(parts)

def draw_box(scr, players, color, abbr, score, ts, start_row):
    h, _ = scr.getmaxyx()
    row  = start_row

    fg, tp, ft, reb, ast, to_, pip = (
        ts.get(k, "-") for k in
        ["fieldGoalPct","threePointFieldGoalPct","freeThrowPct",
         "totalRebounds","assists","turnovers","pointsInPaint"]
    )

    sadd(scr, row, 2,
         f"{abbr}  {score} PTS  |  FG%:{fg}  3P%:{tp}  FT%:{ft}  REB:{reb}  AST:{ast}  TO:{to_}  Paint:{pip}",
         curses.color_pair(color) | curses.A_BOLD)
    row += 1; hl(scr, row); row += 1
    sadd(scr, row, 5, fmt_row(None, header=True), curses.color_pair(C_DIM) | curses.A_BOLD)
    row += 1; hl(scr, row); row += 1

    bench_shown = False
    for p in players:
        if row >= h - 2:
            break
        if not p["starter"] and not bench_shown:
            sadd(scr, row, 2, "-- BENCH " + "-" * 60, curses.color_pair(C_DIM))
            row += 1
            bench_shown = True
        if p["on_court"]:
            sadd(scr, row, 2, "*", curses.color_pair(C_LIVE) | curses.A_BOLD)
            sadd(scr, row, 5, fmt_row(p), curses.color_pair(C_NORMAL) | curses.A_BOLD)
        else:
            sadd(scr, row, 5, fmt_row(p), curses.color_pair(C_DIM))
        row += 1

def draw(scr, tab):
    scr.erase()
    h, w = scr.getmaxyx()

    with LOCK:
        s     = dict(LIVE)
        hp    = list(s["home_players"])
        ap    = list(s["away_players"])
        plays = list(s["plays"])
        hts   = dict(s["home_team_stats"])
        ats   = dict(s["away_team_stats"])

    stype  = s["status_type"]
    period = s["period"]

    if "in" in stype:
        ql         = f"Q{period}" if period <= 4 else f"OT{period-4}"
        status_str = f"IN PROGRESS  |  {ql}  {s['clock']}"
    elif "post" in stype or "final" in s["status"].lower():
        status_str = "FINAL"
    elif "half" in s["status"].lower():
        status_str = "HALFTIME"
    else:
        detail     = s["game_detail"]
        status_str = f"SCHEDULED  |  {detail}" if detail else s["status"].upper()

    title = s["game_title"].upper() if s["game_title"] else "NBA LIVE TRACKER"
    hdr   = f" {title}  |  {status_str}  |  Updated: {s['updated']} "
    sadd(scr, 0, 0, hdr.center(w), curses.color_pair(C_HEADER) | curses.A_BOLD)

    row = 2
    mid = w // 2
    sadd(scr, row, 2,       s["home_name"].upper(), curses.color_pair(C_HOME) | curses.A_BOLD)
    sadd(scr, row, mid - 1, "|",                    curses.color_pair(C_NORMAL))
    sadd(scr, row, mid + 1, s["away_name"].upper(), curses.color_pair(C_AWAY) | curses.A_BOLD)
    row += 1

    sc_line = f"{s['home_score']:>4}   -   {s['away_score']:<4}"
    sadd(scr, row, (w - len(sc_line)) // 2, sc_line, curses.color_pair(C_NORMAL) | curses.A_BOLD)
    row += 1

    hqs, aqs = s["home_qs"], s["away_qs"]
    num_q    = max(len(hqs), len(aqs), 4)
    q_line   = "  ".join(
        f"Q{i+1}: {hqs[i] if i<len(hqs) else '---'}-{aqs[i] if i<len(aqs) else '---'}"
        for i in range(num_q)
    )
    sadd(scr, row, (w - len(q_line)) // 2, q_line, curses.color_pair(C_DIM))
    row += 1; hl(scr, row); row += 1

    tabs = [f" {s['home_abbr']} Box ", f" {s['away_abbr']} Box ", " Play Feed "]
    tx = 2
    for i, t in enumerate(tabs):
        attr = (curses.color_pair(C_HEADER) | curses.A_BOLD) if i == tab else curses.color_pair(C_DIM)
        sadd(scr, row, tx, t, attr)
        tx += len(t) + 1
    row += 1; hl(scr, row); row += 1

    if tab == 0:
        if hp: draw_box(scr, hp, C_HOME, s["home_abbr"], s["home_score"], hts, row)
        else:  sadd(scr, row, 2, "Waiting for box score...", curses.color_pair(C_DIM))
    elif tab == 1:
        if ap: draw_box(scr, ap, C_AWAY, s["away_abbr"], s["away_score"], ats, row)
        else:  sadd(scr, row, 2, "Waiting for box score...", curses.color_pair(C_DIM))
    elif tab == 2:
        sadd(scr, row, 2, "Recent Plays (newest first)", curses.color_pair(C_NORMAL) | curses.A_UNDERLINE)
        row += 1
        for play in plays:
            if row >= h - 2: break
            sadd(scr, row, 2, play, curses.color_pair(C_NORMAL))
            row += 1
        if not plays:
            sadd(scr, row, 2, "Play-by-play will appear once the game starts.", curses.color_pair(C_DIM))

    if s["error"]:
        sadd(scr, h - 2, 2, f"[ERROR] {s['error']}", curses.color_pair(C_WARN))
    else:
        sadd(scr, h - 2, 2,
             f"[1] {s['home_abbr']} Box  [2] {s['away_abbr']} Box  [3] Play Feed  |  * = on court  |  Refresh {REFRESH_SEC}s  |  [Q] Quit",
             curses.color_pair(C_DIM))

    scr.refresh()

def main(scr):
    game = pick_game(scr)
    if game is None:
        return

    with LOCK:
        LIVE["home_name"]  = game["home_name"]
        LIVE["away_name"]  = game["away_name"]
        LIVE["home_abbr"]  = game["home_abbr"]
        LIVE["away_abbr"]  = game["away_abbr"]
        LIVE["game_title"] = game["name"]

    # apply team hex colors to C_HOME/C_AWAY pairs before the first draw
    set_team_colors(game["home_color"], game["home_alt_color"],
                    game["away_color"], game["away_alt_color"])
    scr.nodelay(True)
    scr.timeout(1000)
    tab = 0
    threading.Thread(target=poll, args=(game["id"],), daemon=True).start()
    while True:
        draw(scr, tab)
        key = scr.getch()
        if key in (ord("q"), ord("Q")): break
        elif key == ord("1"): tab = 0
        elif key == ord("2"): tab = 1
        elif key == ord("3"): tab = 2

if __name__ == "__main__":
    curses.wrapper(main)
