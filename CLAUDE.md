# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CLI tool for adding items to Homebox home inventory from Amazon product URLs or local folders.

- **Language:** Python 3.10+
- **Key deps:** playwright, playwright-stealth (v2), requests, pyyaml
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
python -m homebox_tools "https://amazon.com/dp/BXXXXXXXX" --no-manuals     # skip manual search
python -m homebox_tools "https://amazon.com/dp/BXXXXXXXX" --overrides '{"name":"Custom Name"}'
python -m homebox_tools --folder /path/to/product-folder    # local folder mode
python -m homebox_tools --version                           # show version
```

## Architecture

```
homebox_tools/
    __main__.py        -- CLI argparse entry point
    __init__.py        -- package version (__version__)
    schemas.py         -- JSON output schema documentation (doc-as-code)
    lib/
        amazon_scraper.py  -- Playwright headed browser -- Amazon
        name_cleaner.py    -- pure string logic (no deps)
        homebox_client.py  -- requests -- Homebox REST API (retry + token refresh)
        manual_finder.py   -- multi-tier PDF discovery (see Manual Finder below)
        config.py          -- YAML + env var config loading
        models.py          -- ProductData, ManualInfo, SpecField dataclasses
```

**Data flow (URL mode):** URL -> scraper extracts ProductData -> name_cleaner cleans title -> duplicate check (search_items) -> manual_finder searches for PDFs (user confirms) -> homebox_client creates item (POST basic fields) -> GET item for current state -> PUT with extended fields + specs as custom fields -> upload photo -> upload confirmed manuals.

**Data flow (folder mode):** `--folder PATH` -> loads `product.json` (if present) or scans dir for images/PDFs -> skips scraping, proceeds from duplicate check onward.

**Two-phase item creation:** POST `/v1/items` only accepts basic fields (name, description, locationId). Extended fields (manufacturer, model, price, specs) require a follow-up PUT `/v1/items/{id}` with the full item data fetched via GET first. PUT expects flat fields (`locationId`, `tagIds`) — do NOT send nested objects from GET response.

**Field length limits:** name max 255 chars, description max 1000 chars. Enforced in `__main__.py` before POST.

## Config

Default path: `~/.config/homebox-tools/config.yaml` (copy from `config/config.example.yaml`).
Override with env vars: `HOMEBOX_URL`, `HOMEBOX_USERNAME`, `HOMEBOX_PASSWORD`.
Custom path: `python -m homebox_tools --config /path/to/config.yaml`.

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
- HomeboxClient retries on HTTP 429/5xx and connection errors: 3 attempts, exponential backoff (1s, 2s, 4s). On 401: refresh token first, then full re-login.
- Duplicate check: `GET /v1/items?q={model}` before POST to warn on existing matches.

## Manual Finder

Three-tier search strategy:
- **Tier 0** (manufacturer-direct, no rate-limit risk): TP-Link, ASUS, Samsung, APC, Anker — dedicated scrapers + generic URL pattern fallback for unknown brands
- **Tier 1**: Internet Archive manuals collection (`archive.org/advancedsearch`)
- **Tier 2**: DuckDuckGo HTML — ManualsLib, general PDF search, manufacturer site search

Limits: 5 manuals max, 20MB per file, 50MB aggregate. PDF magic-byte validated.

## Amazon Scraping

- Use **headed mode** Playwright (not headless) to avoid anti-bot detection
- `playwright-stealth` v2 API: `Stealth().apply_stealth_async(context)` — applies to the persistent context, NOT per-page
- Auth via Playwright persistent context (`--login` flag for one-time setup)
- Session stored at `~/.config/homebox-tools/amazon-session/`
- Async delays (`asyncio.sleep`) between navigations to avoid blocking the event loop
- Key selectors: `#productTitle`, `#bylineInfo`, `#feature-bullets`, `#productFactsDesktopExpander`, `#aplus_feature_div`

## User Preferences

- Clean product names (strip Amazon SEO junk)
- Always check Amazon order history for actual purchase price
- Always ask for location (no auto-assignment)
- Essential data only: name, price, image, description
- Tags are category-based, suggest from existing list
- Find and attach user manuals/PDFs when possible
