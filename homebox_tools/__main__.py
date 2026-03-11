"""CLI entry point for homebox-tools."""

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import NoReturn

from homebox_tools import __version__
from homebox_tools.lib.config import load_config, Config
from homebox_tools.lib.models import ProductData, ManualInfo
from homebox_tools.lib.name_cleaner import clean_name


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="homebox-tools",
        description="Add items to Homebox inventory from Amazon product URLs.",
    )

    group = parser.add_mutually_exclusive_group()
    group.add_argument("url", nargs="?", help="Amazon product URL to scrape")
    group.add_argument("--folder", type=str, help="Local folder with product files (skip scraping)")
    group.add_argument("--login", action="store_true", help="Interactive Amazon login (one-time setup)")

    parser.add_argument("--location", type=str, help="Location name in Homebox")
    parser.add_argument("--tags", nargs="+", help="Tags to apply to the item")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be created without creating")
    parser.add_argument("--json", action="store_true", dest="json_output", help="Output as JSON (for script integration)")
    parser.add_argument("--overrides", type=str, help="JSON string of field overrides")
    parser.add_argument("--config", type=str, help="Path to config file")
    parser.add_argument("--find-manuals", action="store_true", default=True, help="Search for product manuals (default: true)")
    parser.add_argument("--no-manuals", action="store_false", dest="find_manuals", help="Skip manual search")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    return parser


def _output_error(message: str, code: str, as_json: bool) -> NoReturn:
    if as_json:
        print(json.dumps({"error": code, "message": message}))
    else:
        print(f"Error: {message}", file=sys.stderr)
    sys.exit(1)


async def _run_login(config):
    from homebox_tools.lib.amazon_scraper import AmazonScraper

    scraper = AmazonScraper(session_dir=config.amazon_session_dir)
    await scraper.login_interactive()
    print("Amazon login session saved.")


async def _run_scrape(args, config) -> ProductData:
    from homebox_tools.lib.amazon_scraper import AmazonScraper, ScraperError

    scraper = AmazonScraper(session_dir=config.amazon_session_dir)
    try:
        print("Scraping Amazon...")
        product = await scraper.scrape(args.url)
    except ScraperError as e:
        error_code = str(e)
        if error_code == "cookie_expired":
            _output_error(
                "Amazon session expired. Run: python -m homebox_tools --login",
                "cookie_expired",
                args.json_output,
            )
        elif error_code == "captcha_detected":
            _output_error(
                "Amazon CAPTCHA detected. Try again later or run --login.",
                "captcha_detected",
                args.json_output,
            )
        else:
            _output_error(str(e), "scrape_error", args.json_output)

    product.name = clean_name(product.name)
    return product


def _apply_overrides(product: ProductData, overrides_json: str):
    overrides = json.loads(overrides_json)
    for key, value in overrides.items():
        if hasattr(product, key):
            setattr(product, key, value)


async def _create_item(product: ProductData, args, config):
    from homebox_tools.lib.homebox_client import HomeboxClient, HomeboxError
    from homebox_tools.lib.manual_finder import ManualFinder

    print("Connecting to Homebox...")
    client = HomeboxClient(
        url=config.homebox_url,
        username=config.homebox_username,
        password=config.homebox_password,
    )
    client.login()

    # Check for duplicates
    dupes = client.search_items(product.model or product.name)
    if dupes:
        names = [d.get("name", "?") for d in dupes[:3]]
        product.duplicate_warning = f"Possible duplicates: {', '.join(names)}"
        print(f"Warning: possible duplicates found: {', '.join(names)}")

    # Resolve location
    location_id = None
    if args.location:
        location_id = client.find_location_by_name(args.location)
        if not location_id:
            _output_error(f"Location '{args.location}' not found", "location_not_found", args.json_output)

    if not location_id:
        locations = client.get_locations()
        print("\nAvailable locations:")
        _print_location_tree(locations)
        try:
            loc_name = input("\nEnter location name: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            sys.exit(130)
        location_id = client.find_location_by_name(loc_name, locations)
        if not location_id:
            _output_error(f"Location '{loc_name}' not found", "location_not_found", args.json_output)

    # Resolve tags
    tag_ids = []
    if args.tags:
        existing_tags = client.get_tags()
        tag_map = {t["name"].lower(): t["id"] for t in existing_tags}
        for tag_name in args.tags:
            if tag_name.lower() in tag_map:
                tag_ids.append(tag_map[tag_name.lower()])
            else:
                new_id = client.create_tag(tag_name)
                tag_ids.append(new_id)

    # Find manuals (non-blocking)
    manuals_to_upload = []
    if args.find_manuals and product.model:
        print("Searching for product manuals...")
        finder = ManualFinder()
        found = finder.find_manuals(product.model, product.manufacturer)
        if found:
            print(f"Found {len(found)} manual(s):")
            for m in found:
                print(f"  - {m.name}")
            try:
                confirm = input("Upload these manuals? [Y/n]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\nAborted.")
                sys.exit(130)
            if confirm in ("", "y", "yes"):
                manuals_to_upload = found
                product.manuals = found

    # Homebox field limits: name <= 255, description <= 1000
    name = product.name[:255] if product.name else "Unknown Product"
    description = product.description[:1000] if product.description else ""
    print(f"\nCreating item: {name}")
    item_id = client.create_item(
        name=name,
        description=description,
        location_id=location_id,
        tag_ids=tag_ids or None,
    )

    # Update with extended fields — flatten nested objects for PUT
    item_data = client.get_item(item_id)
    update_data = {
        "id": item_data["id"],
        "name": item_data["name"],
        "description": item_data["description"],
        "quantity": item_data.get("quantity", 1),
        "insured": item_data.get("insured", False),
        "archived": item_data.get("archived", False),
        "serialNumber": item_data.get("serialNumber", ""),
        "modelNumber": item_data.get("modelNumber", ""),
        "manufacturer": item_data.get("manufacturer", ""),
        "lifetimeWarranty": item_data.get("lifetimeWarranty", False),
        "warrantyExpires": item_data.get("warrantyExpires", ""),
        "warrantyDetails": item_data.get("warrantyDetails", ""),
        "purchasePrice": item_data.get("purchasePrice", 0),
        "purchaseTime": item_data.get("purchaseTime", ""),
        "purchaseFrom": item_data.get("purchaseFrom", ""),
        "soldTime": item_data.get("soldTime", ""),
        "soldTo": item_data.get("soldTo", ""),
        "soldPrice": item_data.get("soldPrice", 0),
        "soldNotes": item_data.get("soldNotes", ""),
        "notes": item_data.get("notes", ""),
        "assetId": item_data.get("assetId", ""),
        "syncChildItemsLocations": item_data.get("syncChildItemsLocations", False),
        "locationId": item_data["location"]["id"],
        "tagIds": [t["id"] for t in item_data.get("tags", [])],
        "fields": item_data.get("fields", []),
    }

    if product.manufacturer:
        update_data["manufacturer"] = product.manufacturer
    if product.model:
        update_data["modelNumber"] = product.model
    if product.price is not None:
        update_data["purchasePrice"] = product.price
    if product.purchase_date:
        update_data["purchaseFrom"] = "Amazon"
        update_data["purchaseTime"] = product.purchase_date

    # Add specs as custom fields (preserve existing)
    for spec in product.specs:
        number_value = 0
        if spec.type == "number":
            stripped = re.sub(r"[^\d.]", "", spec.value)
            try:
                number_value = float(stripped) if stripped else 0
            except ValueError:
                number_value = 0
        update_data["fields"].append({
            "name": spec.name,
            "type": spec.type,
            "textValue": spec.value if spec.type == "text" else "",
            "numberValue": number_value,
            "booleanValue": False,
            "timeValue": "",
        })

    client.update_item(item_id, update_data)

    # Upload photo
    if product.image_path:
        print("Uploading product image...")
        client.upload_attachment(item_id, Path(product.image_path), attachment_type="photo", primary=True)

    for manual in manuals_to_upload:
        manual_path = Path(manual.path)
        print(f"Uploading manual: {manual.name} ({manual_path.stat().st_size / 1024:.0f} KB)")
        client.upload_attachment(item_id, manual_path, attachment_type="manual")

    item_url = f"{config.homebox_url}/item/{item_id}"
    print(f"\nItem created: {item_url}")
    return item_url


def _print_location_tree(locations: list[dict], indent: int = 0):
    for loc in locations:
        print(f"{'  ' * indent}{loc['name']}")
        children = loc.get("children", [])
        if children:
            _print_location_tree(children, indent + 1)


def _load_from_folder(folder_path: str) -> ProductData:
    folder = Path(folder_path)
    if not folder.is_dir():
        print(f"Error: {folder_path} is not a directory", file=sys.stderr)
        sys.exit(1)

    product_json = folder / "product.json"
    if product_json.exists():
        data = json.loads(product_json.read_text())
        return ProductData(**data)

    name = folder.name.replace("_", " ").replace("-", " ")
    image_path = None
    manuals = []
    for f in folder.iterdir():
        if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp") and not image_path:
            image_path = str(f)
        elif f.suffix.lower() == ".pdf":
            manuals.append(ManualInfo(path=str(f), name=f.stem))

    return ProductData(name=name, image_path=image_path, manuals=manuals)


def _print_product_summary(product: ProductData):
    print(f"Name: {product.name}")
    if product.manufacturer:
        print(f"Manufacturer: {product.manufacturer}")
    if product.model:
        print(f"Model: {product.model}")
    if product.price is not None:
        print(f"Price: ${product.price:.2f}")
    if product.description:
        desc = product.description[:200] + "..." if len(product.description) > 200 else product.description
        print(f"Description: {desc}")
    if product.image_path:
        print(f"Image: {product.image_path}")
    if product.manuals:
        print(f"Manuals: {len(product.manuals)} found")
    if product.specs:
        print(f"Specs: {len(product.specs)} fields")
    if product.duplicate_warning:
        print(f"Warning: {product.duplicate_warning}")


def main():
    parser = build_parser()
    args = parser.parse_args()

    if not args.url and not args.folder and not args.login:
        parser.print_usage()
        print("Error: provide an Amazon URL, --folder, or --login", file=sys.stderr)
        sys.exit(1)

    try:
        config = load_config(args.config)
    except FileNotFoundError:
        if args.login:
            config = Config(
                homebox_url="",
                homebox_username="",
                homebox_password="",
                amazon_session_dir=str(Path.home() / ".config" / "homebox-tools" / "amazon-session"),
            )
        else:
            _output_error(
                "Config file not found. Copy config/config.example.yaml to ~/.config/homebox-tools/config.yaml",
                "config_not_found",
                getattr(args, "json_output", False),
            )
            return

    if args.login:
        asyncio.run(_run_login(config))
        return

    if args.url:
        product = asyncio.run(_run_scrape(args, config))
    elif args.folder:
        product = _load_from_folder(args.folder)
    else:
        parser.print_usage()
        sys.exit(1)

    if args.overrides:
        _apply_overrides(product, args.overrides)

    if args.dry_run:
        output = product.to_dict()
        if args.json_output:
            print(json.dumps(output, indent=2))
        else:
            _print_product_summary(product)
        return

    asyncio.run(_create_item(product, args, config))


if __name__ == "__main__":
    main()
