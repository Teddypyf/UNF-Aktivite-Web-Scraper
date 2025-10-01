
# UNF Aktivite Web Scraper

This project automatically scrapes UNF event information for KBH, Lyngby, Aalborg, Aarhus, Danmark, and Odense, and generates ICS calendar files with Europe/Copenhagen timezone. Supports automated publishing via GitHub Actions.

## Features

- Login to the UNF event website (supports both CI environment and local interactive login)
- Crawl events for multiple cities, with multi-page support
- Parse event tables or pipe-separated text
- Generate ICS files conforming to the iCalendar standard, including timezone info
- Automated publishing to GitHub Pages

## Usage

### GitHub Actions Automation

- The workflow file `.github/workflows/publish.yml` is scheduled to run several times a day, automatically scraping and publishing to GitHub Pages.
- You must set `UNF_USER` and `UNF_PASS` in the repository Secrets.
- Generated ICS files are uploaded to the `dist` directory and published via Pages.

### Local Run

1. Install dependencies:

	```bash
	pip install -r requirements.txt
	```

2. Run the script:

	```bash
	python unf_events_to_ics.py --out-dir dist --pages 5
	```

	Optional arguments:
	- `--workers N` Number of parallel crawling threads (default 3)
	- `--cache-ttl SECONDS` Page cache time (default 0, off)

## Main Files

- `unf_events_to_ics.py`: Main crawler and ICS generator script
- `.github/workflows/publish.yml`: GitHub Actions automation workflow
- `index.html`: Static page showing update time, file list, and subscription links

## Environment Variables

- `UNF_USER`: UNF login username
- `UNF_PASS`: UNF login password

## Output

- `dist/unf_events_kbh.ics`: KBH events ICS file
- `dist/unf_events_lyngby.ics`: Lyngby events ICS file
- `dist/unf_events_aarhus.ics`: Aarhus events ICS file
- `dist/unf_events_odense.ics`: Odense events ICS file
- `dist/unf_events_aalborg.ics`: Aalborg events ICS file
- `dist/unf_events_danmark.ics`: Danmark events ICS file

---

For a Chinese version, see [README.zh-CN.md](README.zh-CN.md)
