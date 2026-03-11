"""Amazon product page scraper using headed Playwright."""

import asyncio
import re
import random
import tempfile
import time
from pathlib import Path

import requests as http_requests

from homebox_tools.lib.models import ProductData, SpecField


ASIN_RE = re.compile(r"/(?:dp|gp/product)/([A-Z0-9]{10})")
ASIN_SHORT_RE = re.compile(r"amzn\.com/([A-Z0-9]{10})")

# Patterns that indicate Amazon returned an error page instead of a product
_ERROR_PAGE_INDICATORS = [
    "#error-page",
    "img[alt='Dogs of Amazon']",
    "#503-error-message",
]

# Text fragments that indicate the page is an error/unavailable page
_ERROR_TEXT_MARKERS = [
    "sorry, we just need to make sure you're not a robot",
    "page not found",
    "looking for something?",
    "try again later",
]

# Price text patterns indicating unavailability
_UNAVAILABLE_PATTERNS = re.compile(
    r"currently\s+unavailable|unavailable|not\s+available",
    re.IGNORECASE,
)


def extract_asin(url: str) -> str | None:
    m = ASIN_RE.search(url) or ASIN_SHORT_RE.search(url)
    return m.group(1) if m else None


def parse_price_text(text: str | None) -> float | None:
    """Parse a price string into a float, handling edge cases.

    Handles:
    - Standard prices: "$29.99" -> 29.99
    - Prices with commas: "$1,299.99" -> 1299.99
    - Price ranges: "$29.99 - $39.99" -> 29.99 (first price)
    - "Currently unavailable" -> None
    - "list:" prefix: "list: $29.99" -> 29.99
    - Empty/None -> None
    """
    if not text:
        return None

    # Check for unavailability markers
    if _UNAVAILABLE_PATTERNS.search(text):
        return None

    # Strip "list:" prefix (case-insensitive)
    cleaned = re.sub(r"(?i)^list:\s*", "", text.strip())

    # Handle price ranges by taking the first price
    # Split on common range separators before extracting numbers
    range_part = re.split(r"\s*[-–—]\s*\$", cleaned)[0]

    # Extract the numeric portion
    match = re.search(r"[\d,]+\.?\d*", range_part.replace(",", ""))
    if match:
        try:
            return float(match.group())
        except ValueError:
            return None
    return None


class ScraperError(Exception):
    pass


class AmazonScraper:
    def __init__(self, session_dir: str, timeout: float = 60.0):
        """Initialize the scraper.

        Args:
            session_dir: Path to browser session/profile directory.
            timeout: Overall timeout in seconds for the entire scrape
                operation. Defaults to 60s.
        """
        self._session_dir = session_dir
        self._timeout = timeout
        self._browser = None
        self._context = None
        self._page = None

    def _random_delay(self, min_s: float = 2.0, max_s: float = 5.0):
        time.sleep(random.uniform(min_s, max_s))

    async def _launch(self, headless: bool = False):
        from playwright.async_api import async_playwright
        from playwright_stealth import Stealth

        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch_persistent_context(
            user_data_dir=self._session_dir,
            headless=headless,
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        # apply_stealth_async works on the context (persistent or otherwise)
        stealth = Stealth()
        await stealth.apply_stealth_async(self._browser)
        self._page = self._browser.pages[0] if self._browser.pages else await self._browser.new_page()

    async def login_interactive(self):
        """Open browser for user to manually log into Amazon."""
        await self._launch(headless=False)
        await self._page.goto("https://www.amazon.com/gp/css/homepage.html")
        print("Please log into Amazon in the browser window.")
        print("Press Enter here when done...")
        input()
        await self._close()

    async def scrape(self, url: str) -> ProductData:
        asin = extract_asin(url)
        if not asin:
            raise ScraperError(f"Could not extract ASIN from URL: {url}")

        await self._launch(headless=False)
        try:
            return await asyncio.wait_for(
                self._scrape_product(url, asin),
                timeout=self._timeout,
            )
        except asyncio.TimeoutError:
            raise ScraperError(
                f"Scrape timed out after {self._timeout}s for URL: {url}"
            )
        finally:
            await self._close()

    async def _scrape_product(self, url: str, asin: str) -> ProductData:
        page = self._page

        # Attempt page load with one retry on failure
        await self._navigate_with_retry(page, url)

        self._random_delay()

        # Check for sign-in redirect (session expired)
        if "ap/signin" in page.url or "ap/cvf" in page.url:
            await self._close()
            raise ScraperError("cookie_expired")

        # Check for CAPTCHA
        captcha = await page.query_selector("#captchacharacters")
        if captcha:
            await self._close()
            raise ScraperError("captcha_detected")

        # Check for Amazon error/dog page
        if await self._is_error_page(page):
            raise ScraperError(
                f"Amazon returned an error page for URL: {url}"
            )

        title = await self._get_text(page, "#productTitle", url=url)
        if not title:
            title = await self._get_text(page, "h1", url=url)
        brand = await self._extract_brand(page)
        manufacturer, model = await self._extract_product_info(page)
        description = await self._extract_description(page)
        price = await self._extract_price(page)
        image_url = await self._extract_image_url(page)
        specs = await self._extract_specs(page)

        if not manufacturer:
            manufacturer = brand

        # Download image
        image_path = None
        if image_url:
            image_path = await self._download_image(image_url, asin)

        return ProductData(
            name=title or "Unknown Product",
            description=description or "",
            manufacturer=manufacturer,
            model=model,
            price=price,
            image_path=image_path,
            specs=specs,
            asin=asin,
        )

    async def _navigate_with_retry(
        self, page, url: str, max_retries: int = 1
    ):
        """Navigate to a URL, retrying once on load failure or error page."""
        last_error = None
        for attempt in range(1 + max_retries):
            try:
                response = await page.goto(
                    url, timeout=30000, wait_until="domcontentloaded"
                )

                # Check HTTP status from the response
                if response and response.status >= 400:
                    if attempt < max_retries:
                        self._random_delay(3.0, 6.0)
                        continue
                    raise ScraperError(
                        f"Page returned HTTP {response.status} for URL: {url}"
                    )

                # Check if the loaded page is an Amazon error/dog page
                if await self._is_error_page(page):
                    if attempt < max_retries:
                        self._random_delay(3.0, 6.0)
                        continue
                    raise ScraperError(
                        f"Amazon returned an error page for URL: {url}"
                    )

                # Success
                return

            except ScraperError:
                raise
            except Exception as e:
                last_error = e
                if attempt < max_retries:
                    self._random_delay(3.0, 6.0)
                    continue
                raise ScraperError(
                    f"Failed to load page after {1 + max_retries} "
                    f"attempt(s) for URL: {url} — {e}"
                ) from last_error

    async def _is_error_page(self, page) -> bool:
        """Detect whether the current page is an Amazon error/dog page."""
        for selector in _ERROR_PAGE_INDICATORS:
            el = await page.query_selector(selector)
            if el:
                return True

        # Check page body text for error markers
        try:
            body_text = await page.inner_text("body")
            body_lower = body_text.lower()
            for marker in _ERROR_TEXT_MARKERS:
                if marker in body_lower:
                    return True
        except Exception:
            pass

        return False

    async def _get_text(
        self, page, selector: str, *, url: str | None = None
    ) -> str | None:
        try:
            el = await page.wait_for_selector(selector, timeout=5000)
            if el:
                text = await el.inner_text()
                return text.strip()
        except Exception:
            pass
        return None

    async def _extract_brand(self, page) -> str | None:
        text = await self._get_text(page, "#bylineInfo")
        if text:
            text = re.sub(r"^(Visit the |Brand:\s*)", "", text)
            text = re.sub(r"\s*Store$", "", text)
            return text.strip()
        return None

    async def _extract_product_info(self, page) -> tuple[str | None, str | None]:
        manufacturer = None
        model = None
        rows = await page.query_selector_all(
            "#productDetails_techSpec_section_1 tr, "
            "#detailBullets_feature_div li, "
            "#productDetails_detailBullets_sections1 tr"
        )
        for row in rows:
            text = await row.inner_text()
            lower = text.lower()
            if "manufacturer" in lower:
                parts = re.split(r"[\t\n]", text)
                if len(parts) >= 2:
                    manufacturer = parts[-1].strip()
            elif "model" in lower or "item model" in lower:
                parts = re.split(r"[\t\n]", text)
                if len(parts) >= 2:
                    model = parts[-1].strip()
        return manufacturer, model

    async def _extract_description(self, page) -> str | None:
        el = await page.query_selector("#feature-bullets")
        if el:
            items = await el.query_selector_all("li span.a-list-item")
            if items:
                bullets = []
                for item in items:
                    text = (await item.inner_text()).strip()
                    if text and "see more product details" not in text.lower():
                        bullets.append(text)
                if bullets:
                    return "\n".join(f"- {b}" for b in bullets)

        text = await self._get_text(page, "#productFactsDesktopExpander")
        if text:
            return text

        return await self._get_text(page, "#aplus_feature_div")

    async def _extract_price(self, page) -> float | None:
        # Try the primary price selector
        text = await self._get_text(page, "span.a-price > span.a-offscreen")

        # Fallback selectors for alternate page layouts
        if not text:
            text = await self._get_text(page, "#priceblock_ourprice")
        if not text:
            text = await self._get_text(page, "#priceblock_dealprice")
        if not text:
            text = await self._get_text(page, "#availability")

        return parse_price_text(text)

    async def _extract_image_url(self, page) -> str | None:
        img = await page.query_selector("#imgTagWrapperId img, #landingImage")
        if img:
            url = await img.get_attribute("data-old-hires")
            if not url:
                url = await img.get_attribute("src")
            if url:
                url = re.sub(r"\._[A-Z]{2}\d+_", "", url)
                return url
        return None

    async def _extract_specs(self, page) -> list[SpecField]:
        specs = []
        rows = await page.query_selector_all("#productDetails_techSpec_section_1 tr")
        for row in rows:
            header = await row.query_selector("th")
            value = await row.query_selector("td")
            if header and value:
                h_text = (await header.inner_text()).strip()
                v_text = (await value.inner_text()).strip()
                if h_text and v_text:
                    field_type = "number" if re.match(
                        r"^[\d.,]+\s*(lbs?|kg|oz|watts?|W|inches|in|cm|mm|GB|TB|MB|MHz|GHz)",
                        v_text,
                    ) else "text"
                    specs.append(SpecField(name=h_text, value=v_text, type=field_type))
        return specs

    async def _download_image(self, url: str, asin: str) -> str | None:
        try:
            resp = http_requests.get(url, timeout=30)
            if resp.ok:
                suffix = ".jpg"
                if "png" in resp.headers.get("content-type", ""):
                    suffix = ".png"
                path = Path(tempfile.gettempdir()) / f"homebox_{asin}{suffix}"
                path.write_bytes(resp.content)
                return str(path)
        except Exception:
            pass
        return None

    async def _close(self):
        if self._browser:
            await self._browser.close()
        if hasattr(self, "_pw") and self._pw:
            await self._pw.stop()
