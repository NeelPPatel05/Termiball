# Termiball
 - Name subject to Change, Please give me any good name recs please ;_;

A terminal-based NBA live tracker that shows real-time box scores and play-by-play feeds, powered by ESPN's public API.
Initially designed to create a very low and cost-distraction free way of keeping track of a game while seeing stats for each player and team. Running it in the terminal also comes with the added benefit of easy customizability. In other words, if anyone knows a little python they change it to their liking.

---

## Requirements

- Python 3.7 or higher
- An internet connection
- `curl` installed on your system (standard on macOS and Linux; available on Windows 10+)

---

## Installation

### 1. Clone or download the script

Save `termiball.py` somewhere on your machine.

### 2. Install dependencies

**macOS / Linux** — no extra packages needed. Just run it.

**Windows only** — install `windows-curses` first:

```
pip install windows-curses
```

---

## Running the tracker

```
python termiball.py
```

---

## How to use it

When you launch the script, you'll see a list of today's NBA games. Use the keyboard to navigate:

| Key | Action |
|-----|--------|
| `↑` / `K` | Move up |
| `↓` / `J` | Move down |
| `Enter` | Select a game |
| `Q` | Quit |

Once inside a game:

| Key | Action |
|-----|--------|
| `1` | Home team box score |
| `2` | Away team box score |
| `3` | Play-by-play feed |
| `Q` | Quit back to terminal |

Box scores refresh automatically every 15 seconds. Players currently on the court are marked with a `*`.

---

## Troubleshooting

**"No NBA games scheduled today"** — There are no games today, or the ESPN API isn't responding. Try again later.

**Colors look wrong or crash on startup** — Your terminal may not support 256 colors. Try switching to a modern terminal like Windows Terminal, iTerm2, or any xterm-256color terminal.

**`curl` not found** — Install curl or check that it's on your PATH. On Windows, it comes bundled with Windows 10 (1803+) — open a new terminal and try again.

**`ModuleNotFoundError: No module named '_curses'` (Windows)** — Run `pip install windows-curses` and try again.