"""
web/cosb.py — Contest Online ScoreBoard (contestonlinescore.com) live-rank
lookup, used by the Overview tab's "Live Ranking" panel.

COSB has no public read API (only a documented XML spec for the *posting*
side that loggers like N1MM+ already use) — this scrapes the per-callsign
lookup page instead. Researched directly against the live site:

  GET https://contestonlinescore.com/tools/rate/?call={CALLSIGN}
    - 302s to the generic /scoreboard/ landing page when the callsign has
      no live data right now.
    - Otherwise lands on that callsign's actual contest scoreboard.

Landed scoreboard pages are one big <table> with category sections marked
by <tr class="title5"> header rows (category text inside <a> tags, e.g.
"SO-ALL HP CW"), followed by data rows alternating <tr class="tbl1"> /
<tr class="tbl2">. Each data row's cells in order: rank, callsign (inside
an <a href="/tools/rate/?call=XXX">), score, QSO count.

Whatever page COSB actually returns gets walked the same way below, so this
is robust to either path. If no row matches the target callsign anywhere on
the page, that means "no live data right now" — not an error.

This must never be able to break the rest of the app: every failure mode
(network error, COSB redesigning their HTML) is caught and logged, never
raised, so the live-ranking panel just silently shows "unavailable".
"""

from __future__ import annotations

import logging
import re
from typing import Optional
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

RATE_URL = "https://contestonlinescore.com/tools/rate/?call={call}"
SCOREBOARD_URL = "https://contestonlinescore.com/scoreboard/?contest_id={cid}"
TIMEOUT_SECS = 8
USER_AGENT = "VKContestAnalyzer/26.6 (+https://github.com/ezypezy22/vkca_web)"


def fetch_live_rank(callsign: str) -> Optional[dict]:
    """
    Look up `callsign`'s current live rank on Contest Online ScoreBoard.

    Returns a dict {rank, total_in_category, category, score, qsos,
    contest_name, profile_url} on success, or None if there's no live data
    for this callsign right now (not currently posting, between contests,
    etc.) or the lookup/parse failed for any reason.
    """
    callsign = (callsign or "").strip().upper()
    if not callsign:
        return None

    url = RATE_URL.format(call=quote(callsign))
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=TIMEOUT_SECS,
            allow_redirects=True,
        )
        resp.raise_for_status()
    except Exception as e:
        log.info("COSB live-rank request failed for %s: %s", callsign, e)
        return None

    try:
        return _parse_scoreboard(resp.text, callsign, resp.url)
    except Exception as e:
        # Most likely COSB changed their page markup — log it so this is
        # discoverable, but never let a scrape failure affect the rest of
        # the app.
        log.warning("COSB scoreboard parse failed for %s: %s", callsign, e)
        return None


def _parse_scoreboard(html: str, callsign: str, page_url: str) -> Optional[dict]:
    soup = BeautifulSoup(html, "html.parser")

    rows = []  # [(category, rank, call, score, qsos), ...] in document order
    current_category = ""
    for tr in soup.find_all("tr"):
        classes = tr.get("class") or []
        if "title5" in classes:
            td = tr.find("td")
            if td:
                current_category = re.sub(r"\s+", " ", td.get_text(" ", strip=True))
            continue
        if "tbl1" in classes or "tbl2" in classes:
            cells = tr.find_all("td")
            if len(cells) < 4:
                continue
            rank_text = cells[0].get_text(strip=True)
            if not rank_text.isdigit():
                continue
            call_link = cells[1].find("a")
            row_call = (call_link.get_text(strip=True) if call_link
                        else cells[1].get_text(strip=True)).strip().upper()
            if not row_call:
                continue
            score_text = cells[2].get_text(strip=True)
            qsos_text = cells[3].get_text(strip=True)
            rows.append((current_category, int(rank_text), row_call, score_text, qsos_text))

    match = next((r for r in rows if r[2] == callsign), None)
    if match is None:
        return None

    category, rank, _call, score_text, qsos_text = match
    total_in_category = sum(1 for r in rows if r[0] == category)

    # The contest-picker <select> marks the currently-viewed contest with the
    # `selected` attribute, e.g. <option value='2' selected>Closed: ARRL Field
    # Day</option> — strip the "Closed: "/"Coming: " status prefix it adds.
    contest_name = "Contest Online ScoreBoard"
    selected_opt = soup.select_one("select[name='contest_id'] option[selected]")
    if selected_opt:
        text = selected_opt.get_text(strip=True)
        contest_name = re.sub(r"^(Closed|Coming):\s*", "", text).strip() or contest_name

    return {
        "rank": rank,
        "total_in_category": total_in_category,
        "category": category,
        "score": _to_int(score_text),
        "qsos": _to_int(qsos_text),
        "contest_name": contest_name or "Contest Online ScoreBoard",
        "profile_url": page_url,
    }


def _to_int(text: str) -> int:
    try:
        return int(re.sub(r"[^\d]", "", text) or 0)
    except Exception:
        return 0
