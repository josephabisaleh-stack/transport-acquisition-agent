# 🚛 Transport Acquisition Agent

Scans French and Swiss M&A platforms daily for **commissionnaire de transport** companies listed for sale, and sends a curated email digest with only *new* listings.

---

## Sources scanned

| Platform | Country | Notes |
|---|---|---|
| **Fusacq** | 🇫🇷 France | Largest French M&A listing platform |
| **Cession PME** | 🇫🇷 France | SME-focused, good volume |
| **Transentreprise** | 🇫🇷 France | CCI-backed, verified listings |

> 🇨🇭 Switzerland: Fusacq includes Swiss listings. You can add [reprise-entreprise.ch](https://www.reprise-entreprise.ch) as a future source.

---

## Quick start

### 1. Clone & install

```bash
git clone https://github.com/YOUR_USERNAME/transport-agent.git
cd transport-agent
pip install -r requirements.txt
```

### 2. Configure

Edit **`config.py`**:

```python
EMAIL_SENDER      = "you@gmail.com"
EMAIL_PASSWORD    = "xxxx xxxx xxxx xxxx"   # Gmail App Password
EMAIL_RECIPIENTS  = ["you@yourdomain.com"]
```

> **Gmail App Password setup:**
> 1. Enable 2-Factor Authentication on your Google account
> 2. Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
> 3. Create an app password for "Mail" → copy the 16-character password

### 3. Test run

```bash
# Dry run — no email sent, no DB writes
python main.py --dry-run

# Force send email (even with 0 new listings, good for testing)
python main.py --force-email
```

### 4. Schedule it

**Option A — Cron (Linux/Mac server):**

```bash
# Open crontab
crontab -e

# Add this line (runs every day at 8:00 AM)
0 8 * * * cd /path/to/transport-agent && python main.py >> agent.log 2>&1
```

**Option B — GitHub Actions (free, no server needed):**

1. Push the repo to GitHub
2. Go to **Settings → Secrets → Actions**
3. Add two secrets: `EMAIL_SENDER` and `EMAIL_PASSWORD`
4. The workflow in `.github/workflows/daily_scan.yml` runs automatically at 09:00 Paris/Geneva time

---

## Email digest preview

Each email includes:
- **Source** (Fusacq / Cession PME / Transentreprise)
- **Listing title** with a direct link
- **Location** and **price** (when available)
- **Short description**

Only *new* listings are included — ones you've already seen are filtered out via the local SQLite database.

---

## Adding more sources

1. Copy `scrapers/fusacq.py` as a template
2. Implement the `scrape() -> list[dict]` function
3. Import and add it to `main.py` in the `for scraper_module in [...]` list

Each listing dict must have these keys:
```python
{
    "source":      str,   # Platform name
    "title":       str,   # Listing title
    "url":         str,   # Unique URL (used for deduplication)
    "description": str,   # Short excerpt
    "price":       str,   # e.g. "350 000 €" or "N/C"
    "location":    str,   # e.g. "Rhône (69)"
}
```

---

## Project structure

```
transport-agent/
├── main.py              # Orchestrator — run this
├── config.py            # 🔧 Edit this first
├── db.py                # SQLite deduplication
├── email_sender.py      # HTML email builder & sender
├── requirements.txt
├── scrapers/
│   ├── fusacq.py
│   ├── cession_pme.py
│   └── transentreprise.py
└── .github/
    └── workflows/
        └── daily_scan.yml
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| No listings found | Sites may have updated their HTML. Check the selector fallbacks in each scraper. |
| Email not sent | Check your Gmail App Password and that 2FA is enabled. |
| Duplicate listings | Run `python -c "import db; db.init_db()"` to reinitialise the DB. |
| Site returns 403 | Add a delay or rotate the `User-Agent` in `config.py`. |
