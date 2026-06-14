!/usr/bin/env python3
"""termiball — NBA live tracker in the terminal"""

import curses, subprocess, json, time, threading
from datetime import datetime
from assets import PIXEL_DIGITS, LOGO_LINES, BALL_ART, LABEL_MAP, COLS

# ── config ────────────────────────────────────────────────────────────────────
ESPN_SCORE_URL   = "http://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
ESPN_SUMMARY_URL = "http://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={eid}"
REFRESH_SEC = 15

# ── shared live state (written by poll thread, read by draw thread) ───────────
LOCK = threading.Lock()
LIVE = {
    "home_name":"", "away_name":"", "home_abbr":"", "away_abbr":"",
    "home_score":0,  "away_score":0,  "home_qs":[],   "away_qs":[],
    "home_players":[], "away_players":[], "home_team_stats":{}, "away_team_stats":{},
    "plays":[], "period":0, "clock":"--:--",
    "status":"Scheduled", "status_type":"scheduled",
    "game_title":"", "game_detail":"", "updated":"Never", "error":None,
}

# ── curses color pair indices ─────────────────────────────────────────────────
C_HEADER=1; C_HOME=2; C_AWAY=3; C_WARN=4; C_NORMAL=5; C_DIM=6; C_LIVE=7
C_LOGO=8; C_ACCENT=9
HOME_COLOR_IDX=10; AWAY_COLOR_IDX=11

# ── curses helpers ────────────────────────────────────────────────────────────
def sadd(win, y, x, text, attr=0):
    """Safe addstr: clips to window width and swallows curses edge-case errors."""
    h, w = win.getmaxyx()
    if y < 0 or y >= h or x < 0: return
    avail = w - x - 1
    if avail <= 0: return
    try: win.addstr(y, x, str(text)[:avail], attr)
    except curses.error: pass

def hl(win, y, char=None):
    """Draw a full-width horizontal rule at row y."""
    h, w = win.getmaxyx()
    if char is None: char = curses.ACS_HLINE
    if 0 <= y < h:
        try: win.hline(y, 0, char, w-1)
        except curses.error: pass

# ── color setup ───────────────────────────────────────────────────────────────
def _parse_hex(h):
    h = h.lstrip("#")
    if len(h) != 6: return None
    return int(h[0:2],16), int(h[2:4],16), int(h[4:6],16)

def _brightness(h):
    rgb = _parse_hex(h)
    if not rgb: return 0
    r,g,b = rgb
    return (r*299 + g*587 + b*114) // 1000

def _to_curses_rgb(h):
    rgb = _parse_hex(h)
    if not rgb: return None
    r,g,b = rgb
    return (r*1000//255, g*1000//255, b*1000//255)

def set_team_colors(home_hex, home_alt, away_hex, away_alt):
    if not curses.can_change_color() or curses.COLORS < 16: return
    # swap to alt color when primary is near-black (invisible on dark backgrounds)
    def pick(p, a): return a if _brightness(p) < 50 and a else p
    for color_idx, pair, hex_, alt in [
        (HOME_COLOR_IDX, C_HOME, home_hex, home_alt),
        (AWAY_COLOR_IDX, C_AWAY, away_hex, away_alt),
    ]:
        rgb = _to_curses_rgb(pick(hex_, alt)) if hex_ else None
        if rgb:
            curses.init_color(color_idx, *rgb)
            curses.init_pair(pair, color_idx, -1)

def init_colors():
    curses.start_color(); curses.use_default_colors()
    curses.init_pair(C_HEADER, curses.COLOR_BLACK,   curses.COLOR_WHITE)
    curses.init_pair(C_HOME,   curses.COLOR_CYAN,    -1)
    curses.init_pair(C_AWAY,   curses.COLOR_MAGENTA, -1)
    curses.init_pair(C_WARN,   curses.COLOR_RED,     -1)
    curses.init_pair(C_NORMAL, curses.COLOR_WHITE,   -1)
    curses.init_pair(C_DIM,    8,                    -1)
    curses.init_pair(C_LIVE,   curses.COLOR_GREEN,   -1)
    curses.init_pair(C_LOGO,   curses.COLOR_YELLOW,  -1)
    curses.init_pair(C_ACCENT, curses.COLOR_YELLOW,  -1)

# ── pixel font ────────────────────────────────────────────────────────────────
def pixel_number(num_str):
    """Render num_str using the 3×5 block font; returns a list of 5 row-strings."""
    rows = ["","","","",""]
    for ch in num_str:
        g = PIXEL_DIGITS.get(ch, PIXEL_DIGITS['-'])
        for i in range(5): rows[i] += g[i] + " "
    return rows

# ── network ───────────────────────────────────────────────────────────────────
def curl_get(url):
    r = subprocess.run(["curl","-s","--max-time","10",url], capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        raise RuntimeError(f"curl failed rc={r.returncode}")
    return json.loads(r.stdout)

# ── ESPN data parsing ─────────────────────────────────────────────────────────
def parse_players(team_box):
    players = []
    for block in team_box.get("statistics",[]):
        labels = block.get("names",[])
        for entry in block.get("athletes",[]):
            if entry.get("didNotPlay",False): continue
            if not any(v not in ("0","-","0-0","0:00","") for v in entry.get("stats",[])): continue
            athlete = entry.get("athlete",{})
            stat    = {LABEL_MAP.get(l,l.lower()):v for l,v in zip(labels, entry.get("stats",[]))}
            pos_raw = athlete.get("position",{})
            players.append({
                "name":     athlete.get("displayName","?"),
                "pos":      pos_raw.get("abbreviation","-") if isinstance(pos_raw,dict) else str(pos_raw),
                "starter":  entry.get("starter",False),
                "on_court": entry.get("active",False),
                **{k: stat.get(k,"-") for k in ["min","pts","reb","ast","stl","blk","to","fg","3p","ft","pf","pm"]},
            })
    players.sort(key=lambda p:(not p["starter"],-(int(p["pts"]) if str(p["pts"]).lstrip("-").isdigit() else 0)))
    return players

def parse_team_stats(summary, home_abbr):
    hts, ats = {}, {}
    for team in summary.get("boxscore",{}).get("teams",[]):
        abbr  = team.get("team",{}).get("abbreviation","")
        stats = {s["name"]: s.get("displayValue","-") for s in team.get("statistics",[])}
        if abbr == home_abbr: hts = stats
        else: ats = stats
    return hts, ats

def parse_plays(summary):
    plays = []
    for play in summary.get("plays",[])[-40:]:
        text = play.get("text","").strip()
        if not text: continue
        if text.startswith("tu"):   # ESPN prefixes some entries with "tu" (time-update marker)
            text = text[2:]
        if not text: continue
        period = play.get("period",{}).get("number","")
        clock  = str(play.get("clock",{}).get("displayValue",""))
        if clock.startswith("tu"): clock = clock[2:]
        hs, as_ = play.get("homeScore",""), play.get("awayScore","")
        score   = f" [{as_}-{hs}]" if hs != "" else ""
        qlbl    = f"Q{period} {clock}" if period else ""
        entry   = f"{qlbl:<11}{text}{score}"
        # belt-and-suspenders: catch "tu" after any leading whitespace
        ls = entry.lstrip()
        if ls.startswith("tu"):
            entry = entry[:len(entry)-len(ls)] + ls[2:]
        plays.append(entry)
    plays.reverse()
    return plays

def fetch_games():
    games = []
    for e in curl_get(ESPN_SCORE_URL).get("events",[]):
        c    = e["competitions"][0]
        home = next((t for t in c["competitors"] if t["homeAway"]=="home"), c["competitors"][0])
        away = next((t for t in c["competitors"] if t["homeAway"]=="away"), c["competitors"][1])
        st   = e["status"]
        games.append({
            "id": e["id"], "name": e.get("name",""),
            "home_name":      home["team"]["displayName"],
            "away_name":      away["team"]["displayName"],
            "home_abbr":      home["team"]["abbreviation"],
            "away_abbr":      away["team"]["abbreviation"],
            "home_score":     home.get("score",""),
            "away_score":     away.get("score",""),
            "home_color":     home["team"].get("color",""),
            "home_alt_color": home["team"].get("alternateColor",""),
            "away_color":     away["team"].get("color",""),
            "away_alt_color": away["team"].get("alternateColor",""),
            "status_type":    st["type"]["name"],
            "detail":         st["type"].get("shortDetail", st["type"]["description"]),
        })
    return games

# ── background poll thread ────────────────────────────────────────────────────
def poll(event_id):
    """Fetches scoreboard + summary every REFRESH_SEC seconds and updates LIVE."""
    while True:
        try:
            event = comp = None
            for e in curl_get(ESPN_SCORE_URL).get("events",[]):
                if e["id"] == event_id:
                    event, comp = e, e["competitions"][0]
                    break
            if event is None or comp is None:
                with LOCK:
                    LIVE["error"]   = "Game not found in today's schedule."
                    LIVE["updated"] = datetime.now().strftime("%H:%M:%S")
                time.sleep(REFRESH_SEC); continue

            summary = curl_get(ESPN_SUMMARY_URL.format(eid=event_id))
            with LOCK:
                LIVE["error"]   = None
                LIVE["updated"] = datetime.now().strftime("%H:%M:%S")
                st = event["status"]
                LIVE["status_type"] = st["type"]["name"]
                LIVE["status"]      = st["type"]["description"]
                LIVE["period"]      = st.get("period",0)
                LIVE["clock"]       = st.get("displayClock","--:--")
                LIVE["game_detail"] = st["type"].get("shortDetail","")
                LIVE["game_title"]  = event.get("name","")
                home = next(c for c in comp["competitors"] if c["homeAway"]=="home")
                away = next(c for c in comp["competitors"] if c["homeAway"]=="away")
                LIVE["home_name"]  = home["team"]["displayName"]
                LIVE["away_name"]  = away["team"]["displayName"]
                LIVE["home_abbr"]  = home["team"]["abbreviation"]
                LIVE["away_abbr"]  = away["team"]["abbreviation"]
                LIVE["home_score"] = int(home.get("score") or 0)
                LIVE["away_score"] = int(away.get("score") or 0)
                LIVE["home_qs"]    = [int(l["value"]) for l in home.get("linescores",[])]
                LIVE["away_qs"]    = [int(l["value"]) for l in away.get("linescores",[])]
                for tb in summary.get("boxscore",{}).get("players",[]):
                    abbr   = tb.get("team",{}).get("abbreviation","")
                    parsed = parse_players(tb)
                    if abbr == LIVE["home_abbr"]: LIVE["home_players"] = parsed
                    else:                          LIVE["away_players"] = parsed
                hts, ats = parse_team_stats(summary, LIVE["home_abbr"])
                LIVE["home_team_stats"] = hts
                LIVE["away_team_stats"] = ats
                LIVE["plays"]           = parse_plays(summary)
        except Exception as e:
            with LOCK:
                LIVE["error"]   = str(e)[:80]
                LIVE["updated"] = datetime.now().strftime("%H:%M:%S")
        time.sleep(REFRESH_SEC)

# ── box score table ───────────────────────────────────────────────────────────
def fmt_row(p, header=False):
    parts = []
    for hdr, key, w in COLS:
        val = hdr if header else str(p.get(key,"-"))
        parts.append(val[:w].ljust(w) if key=="name" else val[:w].rjust(w))
    return "  ".join(parts)

def draw_box(scr, players, color, abbr, score, ts, row):
    h, _ = scr.getmaxyx()
    fg,tp,ft,reb,ast,to_,pip = (ts.get(k,"-") for k in
        ["fieldGoalPct","threePointFieldGoalPct","freeThrowPct",
         "totalRebounds","assists","turnovers","pointsInPaint"])
    sadd(scr, row, 2,
         f"{abbr}  {score} PTS  │  FG%:{fg}  3P%:{tp}  FT%:{ft}  REB:{reb}  AST:{ast}  TO:{to_}  Paint:{pip}",
         curses.color_pair(color)|curses.A_BOLD)
    row += 1; hl(scr, row); row += 1
    sadd(scr, row, 5, fmt_row(None, header=True), curses.color_pair(C_DIM)|curses.A_BOLD)
    row += 1; hl(scr, row); row += 1
    bench_shown = False
    for p in players:
        if row >= h-2: break
        if not p["starter"] and not bench_shown:
            sadd(scr, row, 2, "── BENCH " + "─"*60, curses.color_pair(C_DIM))
            row += 1; bench_shown = True
        if p["on_court"]:
            sadd(scr, row, 2, "*", curses.color_pair(C_LIVE)|curses.A_BOLD)
            sadd(scr, row, 5, fmt_row(p), curses.color_pair(C_NORMAL)|curses.A_BOLD)
        else:
            sadd(scr, row, 5, fmt_row(p), curses.color_pair(C_DIM))
        row += 1

# ── splash screen / game picker ───────────────────────────────────────────────
def _exit_msg(scr, msg):
    h, _ = scr.getmaxyx()
    scr.erase()
    sadd(scr, h//2,   2, msg,                     curses.color_pair(C_WARN))
    sadd(scr, h//2+1, 2, "Press any key to exit.", curses.color_pair(C_DIM))
    scr.refresh(); scr.getch()

def draw_logo(scr, start_row):
    h, w = scr.getmaxyx()
    for i, line in enumerate(LOGO_LINES):
        sadd(scr, start_row+i, max(0,(w-len(line))//2), line, curses.color_pair(C_LOGO)|curses.A_BOLD)
    ball_x = min(w-16, w-14)
    if ball_x > 0:
        for i, line in enumerate(BALL_ART):
            sadd(scr, start_row+i, ball_x, line, curses.color_pair(C_ACCENT))

def pick_game(scr):
    init_colors()
    curses.curs_set(0); curses.noecho(); scr.nodelay(False)
    h, w = scr.getmaxyx()
    scr.clear()
    draw_logo(scr, 2)
    loading = "  Fetching today's games..."
    sadd(scr, 10, (w-len(loading))//2, loading, curses.color_pair(C_DIM))
    sadd(scr, 11, (w-10)//2, "Loading...", curses.color_pair(C_ACCENT))
    scr.refresh()

    try: games = fetch_games()
    except Exception as e:
        _exit_msg(scr, f"Error fetching schedule: {e}"); return None
    if not games:
        _exit_msg(scr, "No NBA games scheduled today."); return None

    sel = 0
    while True:
        scr.erase(); h, w = scr.getmaxyx()
        draw_logo(scr, 1)
        logo_end = 1 + len(LOGO_LINES)
        subtitle = "  NBA LIVE TRACKER  ·  Select a Game  "
        hint     = "↑/↓  j/k  navigate    ENTER  select    Q  quit"
        sadd(scr, logo_end+1, (w-len(subtitle))//2, subtitle, curses.color_pair(C_HEADER)|curses.A_BOLD)
        sadd(scr, logo_end+2, (w-len(hint))//2,     hint,     curses.color_pair(C_DIM))
        hl(scr, logo_end+3)

        for i, g in enumerate(games):
            row = logo_end + 4 + i*2
            if row >= h-2: break
            stype = g["status_type"]
            if   "in"   in stype: slbl, scol = f"[LIVE]  {g['away_score']}-{g['home_score']}", C_LIVE
            elif "post" in stype: slbl, scol = f"  FINAL  {g['away_score']}-{g['home_score']}", C_DIM
            else:                  slbl, scol = f"  {g['detail']}", C_NORMAL
            matchup = f"{g['away_abbr']}  @  {g['home_abbr']}   {g['away_name']} at {g['home_name']}"
            if i == sel:
                sadd(scr, row, 2, ">", curses.color_pair(C_ACCENT)|curses.A_BOLD)
                sadd(scr, row, 4, matchup, curses.color_pair(C_HEADER)|curses.A_BOLD)
            else:
                sadd(scr, row, 4, matchup, curses.color_pair(C_NORMAL))
            sadd(scr, row, 4+len(matchup)+3, slbl,
                 curses.color_pair(scol)|(curses.A_BOLD if "in" in stype else 0))

        scr.refresh()
        key = scr.getch()
        if   key in (curses.KEY_UP,   ord("k")) and sel > 0:            sel -= 1
        elif key in (curses.KEY_DOWN, ord("j")) and sel < len(games)-1: sel += 1
        elif key in (curses.KEY_ENTER, 10, 13):  return games[sel]
        elif key in (ord("q"), ord("Q")):         return None

# ── scoreboard header ─────────────────────────────────────────────────────────
def draw_scoreboard(scr, s, status_str):
    h, w  = scr.getmaxyx()
    mid   = w // 2
    row   = 2

    # team names flanking center
    home_name = s["home_name"].upper()
    sadd(scr, row, max(2, mid-2-len(home_name)), home_name, curses.color_pair(C_HOME)|curses.A_BOLD)
    sadd(scr, row, mid+2, s["away_name"].upper(),            curses.color_pair(C_AWAY)|curses.A_BOLD)
    row += 1

    # pixel scores: home left-of-center, away right-of-center
    hw     = len(str(s["home_score"])) * 4   # each digit is 3 chars + 1 space
    home_x = max(2, mid - 10 - hw)
    away_x = mid + 10
    for i, (home_r, away_r) in enumerate(zip(pixel_number(str(s["home_score"])),
                                              pixel_number(str(s["away_score"])))):
        sadd(scr, row+i, home_x, home_r, curses.color_pair(C_HOME)|curses.A_BOLD)
        sadd(scr, row+i, away_x, away_r, curses.color_pair(C_AWAY)|curses.A_BOLD)
    sadd(scr, row+1, mid-len(status_str)//2, status_str, curses.color_pair(C_ACCENT)|curses.A_BOLD)
    row += 6

    # per-quarter scores
    hqs, aqs = s["home_qs"], s["away_qs"]
    num_q    = max(len(hqs), len(aqs), 4)
    def qlabel(i): return f"OT{i-3}" if i >= 4 else f"Q{i+1}"
    parts  = [f"{qlabel(i)}: {hqs[i] if i<len(hqs) else '-'}-{aqs[i] if i<len(aqs) else '-'}" for i in range(num_q)]
    q_line = "   ".join(parts)
    sadd(scr, row, (w-len(q_line))//2, q_line, curses.color_pair(C_DIM))
    return row + 2

# ── main draw loop ────────────────────────────────────────────────────────────
def draw(scr, tab):
    scr.erase(); h, w = scr.getmaxyx()
    with LOCK:
        s     = dict(LIVE)
        hp    = list(s["home_players"]); ap  = list(s["away_players"])
        plays = list(s["plays"])
        hts   = dict(s["home_team_stats"]); ats = dict(s["away_team_stats"])

    stype, period = s["status_type"], s["period"]
    if   "in"   in stype:                                 status_str = f"LIVE  {'Q'+str(period) if period<=4 else 'OT'+str(period-4)}  {s['clock']}"
    elif "post" in stype or "final" in s["status"].lower(): status_str = "FINAL"
    elif "half" in s["status"].lower():                    status_str = "HALFTIME"
    else:                                                  status_str = s["game_detail"] or s["status"].upper()

    title = s["game_title"].upper() or "NBA LIVE TRACKER"
    sadd(scr, 0, 0, f"  {title}  │  Updated: {s['updated']}  ".ljust(w),
         curses.color_pair(C_HEADER)|curses.A_BOLD)

    row = draw_scoreboard(scr, s, status_str)
    hl(scr, row); row += 1

    # tab bar
    tabs = [f" 1  {s['home_abbr']} Box Score ", f" 2  {s['away_abbr']} Box Score ", " 3  Play Feed "]
    tx = 2
    for i, t in enumerate(tabs):
        sadd(scr, row, tx, t, curses.color_pair(C_HEADER if i==tab else C_DIM))
        tx += len(t) + 2
    row += 1; hl(scr, row); row += 1

    # tab content
    if tab == 0:
        if hp: draw_box(scr, hp, C_HOME, s["home_abbr"], s["home_score"], hts, row)
        else:  sadd(scr, row, 2, "Waiting for box score...", curses.color_pair(C_DIM))
    elif tab == 1:
        if ap: draw_box(scr, ap, C_AWAY, s["away_abbr"], s["away_score"], ats, row)
        else:  sadd(scr, row, 2, "Waiting for box score...", curses.color_pair(C_DIM))
    elif tab == 2:
        sadd(scr, row, 2, "Recent Plays  (newest first)", curses.color_pair(C_NORMAL)|curses.A_UNDERLINE)
        row += 2
        for play in plays:
            if row >= h-2: break
            scoring = "[" in play
            sadd(scr, row, 2, play, curses.color_pair(C_NORMAL if scoring else C_DIM)|(curses.A_BOLD if scoring else 0))
            row += 1
        if not plays:
            sadd(scr, row, 2, "Play-by-play will appear once the game starts.", curses.color_pair(C_DIM))

    # bottom status bar
    if s["error"]:
        sadd(scr, h-2, 2, f"[!] {s['error']}", curses.color_pair(C_WARN))
    else:
        sadd(scr, h-1, 0,
             f"  1 {s['home_abbr']} Box   2 {s['away_abbr']} Box   3 Play Feed   │  * on court   │  refresh {REFRESH_SEC}s   │  Q quit  ".ljust(w),
             curses.color_pair(C_DIM))
    scr.refresh()

# ── entry point ───────────────────────────────────────────────────────────────
def main(scr):
    game = pick_game(scr)
    if game is None: return
    with LOCK:
        for k in ("home_name","away_name","home_abbr","away_abbr"):
            LIVE[k] = game[k]
        LIVE["game_title"] = game["name"]
    set_team_colors(game["home_color"], game["home_alt_color"],
                    game["away_color"], game["away_alt_color"])
    scr.nodelay(True); scr.timeout(1000)
    threading.Thread(target=poll, args=(game["id"],), daemon=True).start()
    tab = 0
    while True:
        draw(scr, tab)
        key = scr.getch()
        if   key in (ord("q"), ord("Q")): break
        elif key == ord("1"): tab = 0
        elif key == ord("2"): tab = 1
        elif key == ord("3"): tab = 2

if __name__ == "__main__":
    curses.wrapper(main)
