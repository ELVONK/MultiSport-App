# Odibets × Flashscore Match Scraper

Scrapes live football matches from **odibets.com** and **flashscore.co.ke**,
compares kick-off times, and writes `daily_log.csv` split into three sections:

| Section | Contents |
|---------|----------|
| **A — Discrepancy** | Same game on both sites, times differ > 5 min |
| **B — No Discrepancy** | Same game, times agree |
| **C — Unmatched** | Game found on only one source |

The GitHub Actions workflow runs **automatically every 4 hours** and commits
the updated CSV back to this repository.

---

## Repository structure

```
├── .github/
│   └── workflows/
│       └── scraper.yml     ← GitHub Actions workflow (4-hour schedule)
├── scraper.py              ← Main scraping script
├── dashboard.py            ← Streamlit analytics dashboard (run locally)
├── requirements.txt        ← Python dependencies
├── daily_log.csv           ← Auto-updated output (committed by the bot)
└── README.md
```

---

## GitHub Actions setup (one-time)

### 1. Create the repository

```bash
git init
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
```

Add all files, commit, and push:

```bash
git add .
git commit -m "initial commit"
git push -u origin main
```

### 2. Enable workflow write permissions

In your GitHub repo go to:

**Settings → Actions → General → Workflow permissions**

Select **"Read and write permissions"** and click **Save**.

> This allows the bot to commit `daily_log.csv` back to the repo after each run.

### 3. Verify the workflow file is in place

The file `.github/workflows/scraper.yml` must exist on the `main` branch.
GitHub will pick it up automatically — no extra configuration needed.

### 4. Trigger a manual test run

Go to **Actions → Odibets × Flashscore Scraper → Run workflow** to fire
a run immediately without waiting for the 4-hour schedule.

---

## Schedule

The cron expression `0 0,4,8,12,16,20 * * *` runs at these UTC times:

| UTC | Nairobi (EAT, UTC+3) |
|-----|----------------------|
| 00:00 | 03:00 |
| 04:00 | 07:00 |
| 08:00 | 11:00 |
| 12:00 | 15:00 |
| 16:00 | 19:00 |
| 20:00 | 23:00 |

> **Note:** GitHub may delay scheduled runs by up to 15 minutes during
> periods of high load. This is normal.

---

## Downloading the CSV

Two ways to get the latest `daily_log.csv`:

**Option A — from the repo directly**
```
https://raw.githubusercontent.com/YOUR_USERNAME/YOUR_REPO/main/daily_log.csv
```

**Option B — from the Actions artifact**

Go to **Actions → latest run → Artifacts** and download
`daily_log_<run_id>.zip` (kept for 30 days).

---

## Running locally

```bash
# 1. Install dependencies
pip install -r requirements.txt
playwright install chromium

# 2. Single scrape → writes daily_log.csv
python scraper.py

# 3. Continuous loop every 2 hours (for local long-running use)
python scraper.py --loop

# 4. Launch the Streamlit dashboard
streamlit run dashboard.py
```

---

## Configuration

Edit the constants at the top of `scraper.py`:

| Constant | Default | Purpose |
|----------|---------|---------|
| `DISCREPANCY_MIN` | `5` | Minutes threshold to flag a discrepancy |
| `FUZZY_THRESHOLD` | `72` | Team-name match strictness (0–100) |
| `HEADLESS` | `True` | Set `False` to watch the browser |
| `TIMEOUT_MS` | `30000` | Page-load timeout in milliseconds |

---

## Troubleshooting

**Workflow runs but CSV is empty**
- Both sites are JS-heavy; the selectors may need updating if either site
  redesigns. Open a browser with `HEADLESS = False` locally and inspect
  the DOM to update selectors in `scrape_odibets()` / `scrape_flashscore()`.

**"Resource not accessible by integration" push error**
- Check **Settings → Actions → General → Workflow permissions** is set to
  **Read and write**.

**Job times out**
- The `timeout-minutes: 30` limit in the workflow is a safety net. If either
  site is slow, increase it in `scraper.yml`.

**GitHub Actions free-tier limits**
- Public repos: unlimited minutes. Private repos: 2,000 free minutes/month.
  6 runs/day × 30 days × ~5 min/run ≈ 900 minutes — well within the free tier.
