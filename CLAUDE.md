# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CLI tool for adding items to Homebox home inventory from Amazon product URLs or local folders.

- **Language:** Python 3.10+
- **Key deps:** playwright, playwright-stealth, requests, pyyaml
- **Entry point:** `python -m homebox_tools`
- **Package:** `homebox_tools/` with `__main__.py`

## Commands

```bash
make setup                    # install deps + Playwright Chromium
make login                    # one-time Amazon login (opens browser)
python -m pytest tests/ -v    # run all tests
python -m pytest tests/test_name_cleaner.py -v              # single test file
python -m pytest tests/test_homebox_client.py::TestLogin -v  # single test class
python -m homebox_tools --help                               # CLI usage
python -m homebox_tools "https://amazon.com/dp/BXXXXXXXX" --dry-run --json  # test scrape
```

## Architecture

```
__main__.py (CLI argparse)
    ├── amazon_scraper.py  ── Playwright headed browser ── Amazon
    ├── name_cleaner.py    ── pure string logic (no deps)
    ├── homebox_client.py  ── requests ── Homebox REST API
    └── manual_finder.py   ── requests ── DuckDuckGo/ManualsLib

config.py    ── YAML + env var config loading
models.py    ── ProductData, ManualInfo, SpecField dataclasses
```

**Data flow:** URL → scraper extracts ProductData → name_cleaner cleans title → manual_finder searches for PDFs → homebox_client creates item (POST), updates fields (PUT), uploads attachments.

**Two-phase item creation:** POST `/v1/items` only accepts basic fields (name, description, locationId). Extended fields (manufacturer, model, price, specs) require a follow-up PUT `/v1/items/{id}` with the full item data fetched via GET first. PUT expects flat fields (`locationId`, `tagIds`) — do NOT send nested objects from GET response.

**Field length limits:** name max 255 chars, description max 1000 chars. Enforced in `__main__.py` before POST.

## Homebox Instance

- API: REST at `/api/v1/`, auth via bearer token from `/api/v1/users/login`
- Swagger docs at `/api/swagger/` on your Homebox instance
- Tested against Homebox v0.24.2

## API Gotchas

- Login token includes "Bearer " prefix — use as-is in `Authorization` header
- Use `stayLoggedIn: true` for 28-day tokens (default is 7 days)
- Refresh endpoint (`GET /v1/users/refresh`) returns `{"raw": "XXX"}` without Bearer prefix
- POST `/v1/items` only accepts: name, description, locationId, tagIds, parentId, quantity — all other fields ignored
- PUT `/v1/items/{id}` accepts full item data including manufacturer, model, price, custom fields
- Custom fields on PUT are **full replacement** — must send ALL existing fields or they get deleted
- Attachment upload requires `name` form field (422 without it)
- Attachment types: `photo`, `manual`, `warranty`, `receipt`, `attachment`, `thumbnail`
- **PDF attachment bug (v0.24.0–v0.24.1):** Was fixed in v0.24.2. Issue [#1351](https://github.com/sysadminsmedia/homebox/issues/1351) is now closed.

## Amazon Scraping

- Use **headed mode** Playwright (not headless) to avoid anti-bot detection
- `playwright-stealth` v2 API: `Stealth().apply_stealth_async(context)` — applies to the persistent context, NOT per-page
- Auth via Playwright persistent context (`--login` flag for one-time setup)
- Session stored at `~/.config/homebox-tools/amazon-session/`
- Add random 2-5s delays between navigations
- Key selectors: `#productTitle`, `#bylineInfo`, `#feature-bullets`, `#productFactsDesktopExpander`

## User Preferences

- Clean product names (strip Amazon SEO junk)
- Always check Amazon order history for actual purchase price
- Always ask for location (no auto-assignment)
- Essential data only: name, price, image, description
- Tags are category-based, suggest from existing list
- Find and attach user manuals/PDFs when possible
