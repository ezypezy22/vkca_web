"""
web/cosb.py — Contest Online ScoreBoard (contestonlinescore.com) live-rank
lookup, used by the Overview tab's "Live Ranking" panel.

COSB has no public read API (only a documented XML spec for the *posting*
side that loggers like N1MM+ already use) — this scrapes site pages
instead. Researched directly against the live site:

  GET https://contestonlinescore.com/tools/rate/?call={CALLSIGN}
    ALWAYS 302s to the single generic /scoreboard/ landing page — verified
    directly (call with live data vs. call with none both redirect to the
    exact same bare URL). It is NOT a per-callsign search: /scoreboard/
    only ever shows whichever ONE contest COSB currently has flagged
    "selected" in its <select name="contest_id"> dropdown. Since COSB
    tracks dozens of contests concurrently (mini-contests, sprints, DX
    tests, etc. — each with its own contest_id) and a VK contest op is
    essentially never running whatever COSB happens to be featuring at
    that exact moment, relying on this redirect alone means the live-rank
    lookup silently reports "not posting" almost all the time even when
    genuinely live elsewhere on the site — this was the root cause of a
    reported false-negative (GitHub issue #5).

    GET https://contestonlinescore.com/scoreboard/?contest_id={N}
    switches to that specific contest's table (verified) — used below to
    scan the other concurrently-active contests when the featured one
    isn't a match.

Scoreboard pages are one big <table> with category sections marked by
<tr class="title5"> header rows (category text inside <a> tags, e.g.
"SO-ALL HP CW"), followed by data rows alternating <tr class="tbl1"> /
<tr class="tbl2">. Each data row's cells in order: rank, callsign (inside
an <a href="/tools/rate/?call=XXX">), score, QSO count, ...

If no row matches the target callsign on any contest checked, that means
"no live data right now" — not an error.

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

# Upper bound on how many *other* concurrently-active contests get scanned
# when the featured one isn't a match — keeps a single (cached, background-
# thread) lookup from turning into dozens of requests against COSB.
MAX_CONTESTS_SCANNED = 12


def _get(url: str):
    resp = requests.get(
        url, headers={"User-Agent": USER_AGENT},
        timeout=TIMEOUT_SECS, allow_redirects=True,
    )
    resp.raise_for_status()
    return resp


def _other_contest_ids(html: str, skip_id: Optional[str]) -> list[str]:
    """
    Contest ids from the <select name="contest_id"> dropdown, excluding
    `skip_id` (the one already checked) and anything marked "Coming:"
    (not started yet — can't have live data). Order follows the
    dropdown's own order, which puts the most contextually-relevant
    contests near the featured one.
    """
    soup = BeautifulSoup(html, "html.parser")
    sel = soup.select_one("select[name='contest_id']")
    if not sel:
        return []
    ids = []
    for opt in sel.find_all("option"):
        val = opt.get("value")
        if not val or val == skip_id:
            continue
        label = opt.get_text(strip=True)
        if label.startswith("Coming:"):
            continue
        ids.append(val)
    return ids[:MAX_CONTESTS_SCANNED]


def fetch_live_rank(callsign: str) -> Optional[dict]:
    """
    Look up `callsign`'s current live rank on Contest Online ScoreBoard.

    COSB's /tools/rate/?call= redirect always lands on whichever single
    contest it currently has "featured" (see module docstring) — it is
    not a real per-callsign search. So this checks the featured contest
    first (the common/cheap case), then falls back to scanning the other
    concurrently-active contests from the site's own contest picker until
    a match is found or the list is exhausted.

    Returns a dict {rank, total_in_category, category, score, qsos,
    contest_name, profile_url} on success, or None if there's no live data
    for this callsign right now (not currently posting, between contests,
    etc.) or the lookup/parse failed for any reason.
    """
    callsign = (callsign or "").strip().upper()
    if not callsign:
        return None

    try:
        resp = _get(RATE_URL.format(call=quote(callsign)))
    except Exception as e:
        log.info("COSB live-rank request failed for %s: %s", callsign, e)
        return None

    try:
        result = _parse_scoreboard(resp.text, callsign, resp.url)
        if result:
            return result

        soup = BeautifulSoup(resp.text, "html.parser")
        featured_id = soup.select_one("select[name='contest_id'] option[selected]")
        featured_id = featured_id.get("value") if featured_id else None
        for cid in _other_contest_ids(resp.text, featured_id):
            try:
                cresp = _get(SCOREBOARD_URL.format(cid=cid))
                result = _parse_scoreboard(cresp.text, callsign, cresp.url)
                if result:
                    return result
            except Exception as e:
                log.info("COSB scan of contest_id=%s failed for %s: %s", cid, callsign, e)
                continue
        return None
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
    # Day</option> — keep the "Closed: "/"Coming: " status prefix as-is so
    # the Live Ranking tile shows it (helps make sense of a match found via
    # the multi-contest scan above, which can land on a just-ended session).
    contest_name = "Contest Online ScoreBoard"
    selected_opt = soup.select_one("select[name='contest_id'] option[selected]")
    if selected_opt:
        text = selected_opt.get_text(strip=True)
        contest_name = text or contest_name

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
