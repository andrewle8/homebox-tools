# homebox-tools

Tell [Claude Code](https://claude.com/claude-code) "add this to my inventory" with an Amazon
link, and it scrapes the product, cleans the name, hunts down the manuals, and fills out the
[Homebox](https://github.com/sysadminsmedia/homebox) item over the API — image, specs, price,
and PDFs included. Also works as a plain CLI.

## Use with Claude Code

This repo is built to be driven by an agent. It ships a [`CLAUDE.md`](CLAUDE.md) playbook (API
gotchas, field limits, the two-phase item-creation flow) and a `/add-item` slash command, and the
CLI speaks JSON with stable error codes so Claude can run it unattended.

After [setup](#setup), from inside the repo:

```
/add-item https://amazon.com/dp/BXXXXXXXX
```

Or just talk to it:

> add this to my Office inventory and tag it networking — https://amazon.com/dp/BXXXXXXXX

Claude previews with `--dry-run --json`, shows you the cleaned product, asks which Homebox
location it belongs in (it never auto-assigns), then creates the item non-interactively with
`--yes`. The full agent contract:

- `--json` — machine-readable output for every command
- `--dry-run` — full extracted product as JSON, nothing written
- `--overrides '{"name":"..."}'` — patch any scraped field before creating
- `--yes` — non-interactive: auto-confirm manual uploads, never block on a prompt (requires `--location`)
- Stable error codes: `cookie_expired`, `captcha_detected`, `location_required`,
  `location_not_found`, `config_not_found`, `scrape_error`

## What it does

- Scrapes product data from Amazon (title, price, manufacturer, model, specs, image)
- Cleans up SEO-stuffed product names into something readable
- Searches for product manuals (ManualsLib, manufacturer sites, Internet Archive)
- Creates the item in Homebox with all metadata and attachments

## Setup

Requires Python 3.10+ and Playwright (Chromium).

```bash
make setup
cp config/config.example.yaml ~/.config/homebox-tools/config.yaml
# Edit with your Homebox URL and credentials
chmod 0600 ~/.config/homebox-tools/config.yaml
```

One-time Amazon login (saves session to disk):

```bash
make login
```

## Direct CLI usage

```bash
# Add an Amazon product
python -m homebox_tools "https://amazon.com/dp/BXXXXXXXX"

# Preview without creating
python -m homebox_tools "https://amazon.com/dp/BXXXXXXXX" --dry-run

# JSON output for scripting / agents
python -m homebox_tools "https://amazon.com/dp/BXXXXXXXX" --dry-run --json

# Non-interactive (for agents/cron): auto-confirm manuals, fail fast if no location
python -m homebox_tools "https://amazon.com/dp/BXXXXXXXX" --location "Office" --tags electronics networking --yes

# From a local folder with product files
python -m homebox_tools --folder ./my-product/

# Skip manual search
python -m homebox_tools "https://amazon.com/dp/BXXXXXXXX" --no-manuals
```

## Configuration

Config file: `~/.config/homebox-tools/config.yaml`

Environment variables override the config file: `HOMEBOX_URL`, `HOMEBOX_USERNAME`, `HOMEBOX_PASSWORD`.

## How it works

1. Opens Amazon in a real browser (headed Playwright) to avoid bot detection
2. Extracts product data from the page
3. Strips Amazon SEO junk from the title
4. Searches multiple sources for product manuals/PDFs
5. Creates the item in Homebox via REST API
6. Uploads the product image and any manuals as attachments

## License

MIT
