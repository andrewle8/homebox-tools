# homebox-tools

Paste an Amazon URL, get a fully populated [Homebox](https://github.com/sysadminsmedia/homebox) inventory item -- product image, cleaned-up name, specs, price, and manuals included.

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

## Usage

```bash
# Add an Amazon product
python -m homebox_tools "https://amazon.com/dp/BXXXXXXXX"

# Preview without creating
python -m homebox_tools "https://amazon.com/dp/BXXXXXXXX" --dry-run

# JSON output for scripting
python -m homebox_tools "https://amazon.com/dp/BXXXXXXXX" --dry-run --json

# From a local folder with product files
python -m homebox_tools --folder ./my-product/

# Specify location and tags
python -m homebox_tools "https://amazon.com/dp/BXXXXXXXX" --location "Office" --tags electronics networking

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
