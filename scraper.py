"""
Real-Time Match Scraper: Odibets Kenya  ×  Flashscore Kenya
============================================================
Scrapes live/upcoming football matches from both sites, compares kick-off
times, and writes a single CSV (daily_log.csv) split into three sections:

  Section A – DISCREPANCY    : matched games whose times differ > threshold
  Section B – NO DISCREPANCY : matched games whose times agree
  Section C – UNMATCHED      : games found on only one of the two sources

Usage
-----
    pip install playwright pandas rapidfuzz
    playwright install chromium

    # Single run
    python scraper.py

    # Continuous loop every 2 hours (or use cron / Task Scheduler)
    python scraper.py --loop

Dependencies
------------
    playwright   – headless browser (JS-heavy sites)
    pandas       – DataFrame / CSV handling
    rapidfuzz    – fuzzy team-name matching
"""

import argparse
import csv
import re
import time
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
from rapidfuzz import fuzz, process
from playwright.sync_api import sync_playwright, Page, TimeoutError as PWTimeout

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────
OUTPUT_CSV       = Path("daily_log.csv")
DISCREPANCY_MIN  = 5          # minutes difference to flag as discrepancy
FUZZY_THRESHOLD  = 72         # min fuzzy score (0-100) for team-name match
HEADLESS         = True       # set False to watch the browser
TIMEOUT_MS       = 30_000     # page-load timeout in ms
LOOP_INTERVAL_S  = 7_200      # 2 hours

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# DATA MODEL
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class Match:
    source:     str                    # "odibets" | "flashscore"
    league:     str
    team1:      str
    team2:      str
    match_time: str                    # "HH:MM" as shown on site
    match_date: str                    # "YYYY-MM-DD" or empty if not available
    extra:      dict = field(default_factory=dict)   # odds, score, etc.

    @property
    def key(self) -> str:
        """Normalised lookup key: 'team1 vs team2'."""
        return f"{_norm(self.team1)} vs {_norm(self.team2)}"

    @property
    def time_minutes(self) -> Optional[int]:
        """Kick-off time as minutes since midnight, or None if unparseable."""
        m = re.match(r"(\d{1,2}):(\d{2})", self.match_time.strip())
        if m:
            return int(m.group(1)) * 60 + int(m.group(2))
        return None


def _norm(name: str) -> str:
    """Lower-case, strip punctuation/extra spaces for fuzzy comparison."""
    name = name.lower().strip()
    name = re.sub(r"[^a-z0-9 ]", " ", name)
    return re.sub(r"\s+", " ", name).strip()


# ─────────────────────────────────────────────────────────────────────────────
# SCRAPER  – ODIBETS
# ─────────────────────────────────────────────────────────────────────────────
def scrape_odibets(page: Page) -> list[Match]:
    """
    Navigate to odibets.com and extract today's / live football matches.
    Odibets is a React SPA; we wait for the match rows to appear then
    parse team names, kick-off times, leagues, and 1X2 odds.
    """
    matches: list[Match] = []

    try:
        log.info("Odibets → loading page …")
        page.goto("https://odibets.com/football", timeout=TIMEOUT_MS, wait_until="domcontentloaded")

        # Accept cookies / age-gate if present
        for sel in ["button:has-text('Accept')", "button:has-text('OK')", "#accept-cookies"]:
            try:
                page.click(sel, timeout=3_000)
            except PWTimeout:
                pass

        # Wait for at least one match card
        try:
            page.wait_for_selector(".event-row, .match-row, [class*='event'], [class*='game-row']",
                                   timeout=15_000)
        except PWTimeout:
            log.warning("Odibets → no match rows found within timeout")
            return matches

        # -----------------------------------------------------------------
        # Extract via JavaScript evaluation (works regardless of class-name
        # obfuscation because we read text content and aria labels)
        # -----------------------------------------------------------------
        raw = page.evaluate("""
        () => {
            const results = [];

            // Strategy 1: look for elements that contain 'vs' or a known separator
            const rows = document.querySelectorAll(
                '[class*="event"], [class*="match"], [class*="game"], [class*="fixture"]'
            );

            rows.forEach(row => {
                const text = row.innerText || '';
                if (!text.includes('vs') && !text.includes('v.') && text.split('\\n').length < 3) return;

                const timeEl  = row.querySelector('[class*="time"], [class*="kick"], time');
                const leagueEl = row.querySelector('[class*="league"], [class*="competition"], [class*="sport"]');
                const teamEls  = row.querySelectorAll('[class*="team"], [class*="name"]');

                // Odds buttons (1, X, 2)
                const oddEls = row.querySelectorAll('[class*="odd"], button');
                const odds = Array.from(oddEls).map(el => el.innerText.trim()).filter(t => /^\\d+\\.\\d+$/.test(t));

                results.push({
                    time:   timeEl   ? timeEl.innerText.trim()   : '',
                    league: leagueEl ? leagueEl.innerText.trim() : '',
                    teams:  Array.from(teamEls).map(el => el.innerText.trim()),
                    odds:   odds.slice(0, 3),
                    full:   text.trim(),
                });
            });
            return results;
        }
        """)

        today = datetime.now().strftime("%Y-%m-%d")

        for item in raw:
            teams = [t for t in item.get("teams", []) if t and len(t) > 1]
            # Fall back to parsing "full" text for team names
            if len(teams) < 2:
                parts = re.split(r"\bvs\.?\b|\bv\b", item["full"], flags=re.I)
                teams = [p.strip().split("\n")[0] for p in parts if p.strip()]

            if len(teams) < 2:
                continue

            kick = item.get("time", "")
            # keep only "HH:MM" part
            kick_m = re.search(r"\d{1,2}:\d{2}", kick)
            kick_str = kick_m.group() if kick_m else kick.strip()

            league = item.get("league", "").split("\n")[0].strip()
            odds   = item.get("odds", [])

            matches.append(Match(
                source="odibets",
                league=league,
                team1=teams[0],
                team2=teams[1],
                match_time=kick_str,
                match_date=today,
                extra={
                    "odd_1": odds[0] if len(odds) > 0 else "",
                    "odd_x": odds[1] if len(odds) > 1 else "",
                    "odd_2": odds[2] if len(odds) > 2 else "",
                },
            ))

        log.info(f"Odibets → {len(matches)} matches scraped")

    except Exception as exc:
        log.error(f"Odibets scrape failed: {exc}")

    return matches


# ─────────────────────────────────────────────────────────────────────────────
# SCRAPER  – FLASHSCORE
# ─────────────────────────────────────────────────────────────────────────────
def scrape_flashscore(page: Page) -> list[Match]:
    """
    Navigate to flashscore.co.ke and extract today's football matches.
    Flashscore pushes data via its own binary WebSocket protocol, but
    the rendered DOM is queryable once the page settles.
    """
    matches: list[Match] = []

    try:
        log.info("Flashscore → loading page …")
        page.goto("https://www.flashscore.co.ke/football/", timeout=TIMEOUT_MS,
                  wait_until="domcontentloaded")

        for sel in ["button#onetrust-accept-btn-handler", "button:has-text('Accept')",
                    ".close-cookie-consent"]:
            try:
                page.click(sel, timeout=3_000)
            except PWTimeout:
                pass

        # Wait for match list
        try:
            page.wait_for_selector(".event__match, [class*='sportName'], [id*='g_1_']",
                                   timeout=20_000)
        except PWTimeout:
            log.warning("Flashscore → match list didn't appear within timeout")
            return matches

        # Give JS a moment to finish hydrating
        page.wait_for_timeout(2_000)

        raw = page.evaluate("""
        () => {
            const results = [];

            // Flashscore renders each match in a div with id like "g_1_XXXXXXXX"
            // and uses classes event__match--scheduled / --live
            const matchDivs = document.querySelectorAll('[id^="g_1_"], .event__match');

            matchDivs.forEach(div => {
                // Time
                const timeEl = div.querySelector('.event__time, [class*="time"]');
                const time   = timeEl ? timeEl.innerText.trim() : '';

                // Teams
                const homeEl = div.querySelector('.event__homeParticipant, .event__participant--home, [class*="home"]');
                const awayEl = div.querySelector('.event__awayParticipant, .event__participant--away, [class*="away"]');

                const home = homeEl ? homeEl.innerText.trim() : '';
                const away = awayEl ? awayEl.innerText.trim() : '';

                // Score (if live)
                const scoreHomeEl = div.querySelector('.event__score--home, [class*="score-home"]');
                const scoreAwayEl = div.querySelector('.event__score--away, [class*="score-away"]');
                const scoreHome   = scoreHomeEl ? scoreHomeEl.innerText.trim() : '';
                const scoreAway   = scoreAwayEl ? scoreAwayEl.innerText.trim() : '';

                // League: walk up to a header row
                let league = '';
                let node = div.previousElementSibling;
                while (node) {
                    const cls = node.className || '';
                    if (cls.includes('event__header') || cls.includes('league') || cls.includes('category')) {
                        league = node.innerText.trim().split('\\n')[0];
                        break;
                    }
                    node = node.previousElementSibling;
                }

                if (home && away) {
                    results.push({ time, home, away, league, scoreHome, scoreAway });
                }
            });
            return results;
        }
        """)

        today = datetime.now().strftime("%Y-%m-%d")

        for item in raw:
            kick = item.get("time", "")
            # Flashscore shows "HH:MM" for scheduled and "45'" etc. for live
            kick_m = re.search(r"\d{1,2}:\d{2}", kick)
            kick_str = kick_m.group() if kick_m else kick.strip()

            matches.append(Match(
                source="flashscore",
                league=item.get("league", "").strip(),
                team1=item.get("home", "").strip(),
                team2=item.get("away", "").strip(),
                match_time=kick_str,
                match_date=today,
                extra={
                    "score_home": item.get("scoreHome", ""),
                    "score_away": item.get("scoreAway", ""),
                },
            ))

        log.info(f"Flashscore → {len(matches)} matches scraped")

    except Exception as exc:
        log.error(f"Flashscore scrape failed: {exc}")

    return matches


# ─────────────────────────────────────────────────────────────────────────────
# MATCHING ENGINE
# ─────────────────────────────────────────────────────────────────────────────
def fuzzy_match_teams(query: str, candidates: list[str]) -> Optional[str]:
    """Return the best matching key from candidates, or None if below threshold."""
    if not candidates:
        return None
    result = process.extractOne(query, candidates, scorer=fuzz.token_sort_ratio)
    if result and result[1] >= FUZZY_THRESHOLD:
        return result[0]
    return None


def compare_matches(odi_matches: list[Match],
                    flash_matches: list[Match]) -> tuple[list[dict], list[dict], list[dict]]:
    """
    Returns three lists of row-dicts:
        discrepancy    – same game, kick-off time differs > DISCREPANCY_MIN
        no_discrepancy – same game, kick-off times agree (or both missing)
        unmatched      – game exists on only one source
    """
    discrepancy:    list[dict] = []
    no_discrepancy: list[dict] = []
    unmatched:      list[dict] = []

    flash_index = {m.key: m for m in flash_matches}
    flash_keys  = list(flash_index.keys())
    matched_flash_keys: set[str] = set()

    for om in odi_matches:
        # Exact key match first, then fuzzy
        fkey = om.key if om.key in flash_index else fuzzy_match_teams(om.key, flash_keys)

        if fkey and fkey in flash_index:
            fm = flash_index[fkey]
            matched_flash_keys.add(fkey)

            ot = om.time_minutes
            ft = fm.time_minutes

            if ot is not None and ft is not None:
                diff = abs(ot - ft)
            else:
                diff = None

            row = _build_row(om, fm, diff)

            if diff is not None and diff > DISCREPANCY_MIN:
                discrepancy.append(row)
            else:
                no_discrepancy.append(row)
        else:
            # Odibets only
            unmatched.append(_build_unmatched_row(om))

    # Flashscore-only games
    for fkey, fm in flash_index.items():
        if fkey not in matched_flash_keys:
            unmatched.append(_build_unmatched_row(fm))

    return discrepancy, no_discrepancy, unmatched


def _build_row(om: Match, fm: Match, diff: Optional[int]) -> dict:
    ot = om.time_minutes
    ft = fm.time_minutes
    return {
        "Team1":                  om.team1,
        "Team2":                  om.team2,
        "League":                 om.league or fm.league,
        "Odibets_Time":           om.match_time,
        "Flashscore_Time":        fm.match_time,
        "Difference (minutes)":   diff if diff is not None else "",
        "Odibets_Date":           om.match_date,
        "Flashscore_Date":        fm.match_date,
        "Odibets_Odd_1":          om.extra.get("odd_1", ""),
        "Odibets_Odd_X":          om.extra.get("odd_x", ""),
        "Odibets_Odd_2":          om.extra.get("odd_2", ""),
        "Flashscore_Score":       f"{fm.extra.get('score_home','')} - {fm.extra.get('score_away','')}".strip(" -"),
        "Timestamp":              datetime.now().isoformat(timespec="seconds"),
    }


def _build_unmatched_row(m: Match) -> dict:
    return {
        "Team1":                  m.team1,
        "Team2":                  m.team2,
        "League":                 m.league,
        "Odibets_Time":           m.match_time if m.source == "odibets"    else "",
        "Flashscore_Time":        m.match_time if m.source == "flashscore" else "",
        "Difference (minutes)":   "",
        "Odibets_Date":           m.match_date if m.source == "odibets"    else "",
        "Flashscore_Date":        m.match_date if m.source == "flashscore" else "",
        "Odibets_Odd_1":          m.extra.get("odd_1", "") if m.source == "odibets" else "",
        "Odibets_Odd_X":          m.extra.get("odd_x", "") if m.source == "odibets" else "",
        "Odibets_Odd_2":          m.extra.get("odd_2", "") if m.source == "odibets" else "",
        "Flashscore_Score":       f"{m.extra.get('score_home','')} - {m.extra.get('score_away','')}".strip(" -")
                                  if m.source == "flashscore" else "",
        "Timestamp":              datetime.now().isoformat(timespec="seconds"),
        "Source":                 m.source,
    }


# ─────────────────────────────────────────────────────────────────────────────
# CSV WRITER
# ─────────────────────────────────────────────────────────────────────────────
COLUMNS = [
    "Team1", "Team2", "League",
    "Odibets_Time", "Flashscore_Time", "Difference (minutes)",
    "Odibets_Date", "Flashscore_Date",
    "Odibets_Odd_1", "Odibets_Odd_X", "Odibets_Odd_2",
    "Flashscore_Score", "Timestamp", "Source",
]


def write_csv(discrepancy: list[dict],
              no_discrepancy: list[dict],
              unmatched: list[dict]) -> None:
    """
    Write a single CSV with three clearly labelled sections separated by
    blank lines and section-header rows.
    """
    sections = [
        ("=== SECTION A: GAMES WITH DISCREPANCY ===",    discrepancy),
        ("=== SECTION B: GAMES WITHOUT DISCREPANCY ===", no_discrepancy),
        ("=== SECTION C: UNMATCHED GAMES ===",           unmatched),
    ]

    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)

        for label, rows in sections:
            # Section header spanning all columns
            writer.writerow([label] + [""] * (len(COLUMNS) - 1))
            # Column headers
            writer.writerow(COLUMNS)
            # Data rows
            if rows:
                for row in rows:
                    writer.writerow([row.get(c, "") for c in COLUMNS])
            else:
                writer.writerow(["(no records)"] + [""] * (len(COLUMNS) - 1))
            # Blank separator
            writer.writerow([])

    total = len(discrepancy) + len(no_discrepancy) + len(unmatched)
    log.info(
        f"CSV written → {OUTPUT_CSV}  |  "
        f"Discrepancy: {len(discrepancy)}  "
        f"No-discrepancy: {len(no_discrepancy)}  "
        f"Unmatched: {len(unmatched)}  "
        f"Total: {total}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# MAIN PIPELINE
# ─────────────────────────────────────────────────────────────────────────────
def run_once() -> None:
    log.info("=" * 60)
    log.info(f"Run started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("=" * 60)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=HEADLESS,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="en-KE",
            timezone_id="Africa/Nairobi",
            viewport={"width": 1280, "height": 800},
        )
        context.set_extra_http_headers({
            "Accept-Language": "en-KE,en;q=0.9",
        })

        # ── Odibets ────────────────────────────────────────────────────────
        odi_page = context.new_page()
        odi_matches = scrape_odibets(odi_page)
        odi_page.close()

        # ── Flashscore ─────────────────────────────────────────────────────
        flash_page = context.new_page()
        flash_matches = scrape_flashscore(flash_page)
        flash_page.close()

        browser.close()

    # ── Compare & output ───────────────────────────────────────────────────
    discrepancy, no_discrepancy, unmatched = compare_matches(odi_matches, flash_matches)
    write_csv(discrepancy, no_discrepancy, unmatched)
    log.info("Run complete.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Odibets × Flashscore match scraper")
    parser.add_argument(
        "--loop", action="store_true",
        help=f"Run continuously every {LOOP_INTERVAL_S // 3600} hours"
    )
    args = parser.parse_args()

    if args.loop:
        while True:
            try:
                run_once()
            except Exception as exc:
                log.error(f"Unexpected error in run loop: {exc}", exc_info=True)
            log.info(f"Sleeping {LOOP_INTERVAL_S // 3600}h until next run …")
            time.sleep(LOOP_INTERVAL_S)
    else:
        run_once()


if __name__ == "__main__":
    main()
