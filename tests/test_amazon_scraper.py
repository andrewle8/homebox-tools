import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

from homebox_tools.lib.amazon_scraper import (
    AmazonScraper,
    ScraperError,
    extract_asin,
    parse_price_text,
)


# ---------------------------------------------------------------------------
# extract_asin tests (unchanged from original)
# ---------------------------------------------------------------------------
class TestExtractAsin:
    def test_standard_dp_url(self):
        assert extract_asin("https://www.amazon.com/dp/B0BSHF7WHN") == "B0BSHF7WHN"

    def test_product_url_with_title(self):
        url = "https://www.amazon.com/ASUS-ROG-Rapture-GT-AXE16000/dp/B09RXK9N5Q/ref=sr_1_1"
        assert extract_asin(url) == "B09RXK9N5Q"

    def test_short_url(self):
        assert extract_asin("https://amzn.com/B0BSHF7WHN") == "B0BSHF7WHN"

    def test_invalid_url_returns_none(self):
        assert extract_asin("https://example.com/not-amazon") is None

    def test_gp_product_url(self):
        url = "https://www.amazon.com/gp/product/B0BSHF7WHN"
        assert extract_asin(url) == "B0BSHF7WHN"

    def test_url_with_query_params(self):
        url = "https://www.amazon.com/dp/B0BSHF7WHN?th=1&psc=1"
        assert extract_asin(url) == "B0BSHF7WHN"


# ---------------------------------------------------------------------------
# parse_price_text tests (pure function, no mocks needed)
# ---------------------------------------------------------------------------
class TestParsePriceText:
    def test_standard_price(self):
        assert parse_price_text("$29.99") == 29.99

    def test_price_with_commas(self):
        assert parse_price_text("$1,299.99") == 1299.99

    def test_price_range_takes_first(self):
        assert parse_price_text("$29.99 - $39.99") == 29.99

    def test_price_range_with_en_dash(self):
        assert parse_price_text("$29.99 \u2013 $39.99") == 29.99

    def test_price_range_with_em_dash(self):
        assert parse_price_text("$29.99 \u2014 $39.99") == 29.99

    def test_currently_unavailable_returns_none(self):
        assert parse_price_text("Currently unavailable") is None

    def test_currently_unavailable_mixed_case(self):
        assert parse_price_text("Currently Unavailable") is None

    def test_not_available(self):
        assert parse_price_text("Not Available") is None

    def test_unavailable_standalone(self):
        assert parse_price_text("Unavailable") is None

    def test_list_prefix(self):
        assert parse_price_text("list: $29.99") == 29.99

    def test_list_prefix_uppercase(self):
        assert parse_price_text("List: $49.99") == 49.99

    def test_list_prefix_no_space(self):
        assert parse_price_text("list:$29.99") == 29.99

    def test_none_returns_none(self):
        assert parse_price_text(None) is None

    def test_empty_string_returns_none(self):
        assert parse_price_text("") is None

    def test_no_numeric_returns_none(self):
        assert parse_price_text("free") is None

    def test_whole_dollar(self):
        assert parse_price_text("$100") == 100.0

    def test_large_price_with_commas(self):
        assert parse_price_text("$12,345.67") == 12345.67


# ---------------------------------------------------------------------------
# Helpers for mocking Playwright
# ---------------------------------------------------------------------------
def _make_mock_page(
    *,
    url: str = "https://www.amazon.com/dp/B0BSHF7WHN",
    title_text: str | None = "Test Product",
    price_text: str | None = "$29.99",
    has_captcha: bool = False,
    is_signin: bool = False,
    error_page_selector: str | None = None,
    body_text: str = "",
    goto_side_effect=None,
    goto_response_status: int = 200,
):
    """Build a mock Playwright page with configurable behavior."""
    page = AsyncMock()

    # page.url property
    if is_signin:
        type(page).url = PropertyMock(return_value="https://www.amazon.com/ap/signin?openid")
    else:
        type(page).url = PropertyMock(return_value=url)

    # page.goto returns a response object
    response = AsyncMock()
    response.status = goto_response_status
    if goto_side_effect:
        page.goto = AsyncMock(side_effect=goto_side_effect)
    else:
        page.goto = AsyncMock(return_value=response)

    # page.query_selector — contextual mock
    async def mock_query_selector(selector):
        if selector == "#captchacharacters":
            if has_captcha:
                return AsyncMock()
            return None
        if error_page_selector and selector == error_page_selector:
            return AsyncMock()
        # For error page indicator selectors, return None by default
        if selector in (
            "#error-page",
            "img[alt='Dogs of Amazon']",
            "#503-error-message",
        ):
            return None
        if selector == "#imgTagWrapperId img, #landingImage":
            img = AsyncMock()
            img.get_attribute = AsyncMock(side_effect=lambda attr: {
                "data-old-hires": "https://images-na.ssl-images-amazon.com/images/I/test.jpg",
                "src": None,
            }.get(attr))
            return img
        if selector == "#feature-bullets":
            return None
        return None

    page.query_selector = AsyncMock(side_effect=mock_query_selector)
    page.query_selector_all = AsyncMock(return_value=[])

    # page.inner_text for body checks
    async def mock_inner_text(selector):
        if selector == "body":
            return body_text
        return ""

    page.inner_text = AsyncMock(side_effect=mock_inner_text)

    # page.wait_for_selector — return elements for title/price etc.
    async def mock_wait_for_selector(selector, timeout=5000):
        if selector == "#productTitle" and title_text is not None:
            el = AsyncMock()
            el.inner_text = AsyncMock(return_value=title_text)
            return el
        if selector == "span.a-price > span.a-offscreen" and price_text is not None:
            el = AsyncMock()
            el.inner_text = AsyncMock(return_value=price_text)
            return el
        if selector == "#bylineInfo":
            return None
        if selector == "#productFactsDesktopExpander":
            return None
        if selector == "#aplus_feature_div":
            return None
        if selector == "#priceblock_ourprice":
            return None
        if selector == "#priceblock_dealprice":
            return None
        if selector == "#availability":
            return None
        # For h1 fallback when productTitle is missing
        if selector == "h1" and title_text is None:
            return None
        raise Exception(f"Selector {selector} not found")

    page.wait_for_selector = AsyncMock(side_effect=mock_wait_for_selector)

    return page


def _make_scraper(timeout: float = 60.0) -> AmazonScraper:
    """Create a scraper instance with mocked internals."""
    scraper = AmazonScraper(session_dir="/tmp/test-session", timeout=timeout)
    # Prevent actual browser launch
    scraper._launch = AsyncMock()
    scraper._close = AsyncMock()
    scraper._random_delay = MagicMock()
    return scraper


# ---------------------------------------------------------------------------
# Timeout handling tests
# ---------------------------------------------------------------------------
class TestTimeout:
    def test_scraper_default_timeout(self):
        scraper = AmazonScraper(session_dir="/tmp/test")
        assert scraper._timeout == 60.0

    def test_scraper_custom_timeout(self):
        scraper = AmazonScraper(session_dir="/tmp/test", timeout=30.0)
        assert scraper._timeout == 30.0

    def test_scrape_timeout_raises_scraper_error(self):
        scraper = _make_scraper(timeout=0.01)

        async def slow_scrape(url, asin):
            await asyncio.sleep(10)

        scraper._scrape_product = slow_scrape

        with pytest.raises(ScraperError, match="timed out"):
            asyncio.run(
                scraper.scrape("https://www.amazon.com/dp/B0BSHF7WHN")
            )

    def test_timeout_error_includes_url(self):
        scraper = _make_scraper(timeout=0.01)
        target_url = "https://www.amazon.com/dp/B0BSHF7WHN"

        async def slow_scrape(url, asin):
            await asyncio.sleep(10)

        scraper._scrape_product = slow_scrape

        with pytest.raises(ScraperError, match=target_url):
            asyncio.run(
                scraper.scrape(target_url)
            )


# ---------------------------------------------------------------------------
# Error message quality tests
# ---------------------------------------------------------------------------
class TestErrorMessages:
    def test_invalid_asin_includes_url(self):
        scraper = _make_scraper()
        with pytest.raises(ScraperError, match="https://example.com/bad"):
            asyncio.run(
                scraper.scrape("https://example.com/bad")
            )

    def test_http_error_includes_url_and_status(self):
        scraper = _make_scraper()
        page = _make_mock_page(goto_response_status=503)
        scraper._page = page

        with pytest.raises(ScraperError, match="HTTP 503"):
            asyncio.run(
                scraper._navigate_with_retry(
                    page,
                    "https://www.amazon.com/dp/B0BSHF7WHN",
                    max_retries=0,
                )
            )

    def test_http_error_includes_url(self):
        scraper = _make_scraper()
        url = "https://www.amazon.com/dp/B0BSHF7WHN"
        page = _make_mock_page(goto_response_status=503)
        scraper._page = page

        with pytest.raises(ScraperError, match=url):
            asyncio.run(
                scraper._navigate_with_retry(page, url, max_retries=0)
            )


# ---------------------------------------------------------------------------
# Price extraction robustness tests (via _extract_price mock)
# ---------------------------------------------------------------------------
class TestPriceExtraction:
    def test_standard_price(self):
        scraper = _make_scraper()
        page = _make_mock_page(price_text="$29.99")
        scraper._page = page

        result = asyncio.run(
            scraper._extract_price(page)
        )
        assert result == 29.99

    def test_price_range_first_price(self):
        scraper = _make_scraper()
        page = _make_mock_page(price_text="$29.99 - $39.99")
        scraper._page = page

        result = asyncio.run(
            scraper._extract_price(page)
        )
        assert result == 29.99

    def test_currently_unavailable_returns_none(self):
        scraper = _make_scraper()
        page = _make_mock_page(price_text="Currently unavailable")
        scraper._page = page

        result = asyncio.run(
            scraper._extract_price(page)
        )
        assert result is None

    def test_list_prefix_stripped(self):
        scraper = _make_scraper()
        page = _make_mock_page(price_text="list: $49.99")
        scraper._page = page

        result = asyncio.run(
            scraper._extract_price(page)
        )
        assert result == 49.99

    def test_no_price_element_returns_none(self):
        scraper = _make_scraper()
        page = _make_mock_page(price_text=None)
        scraper._page = page

        result = asyncio.run(
            scraper._extract_price(page)
        )
        assert result is None

    def test_price_with_commas(self):
        scraper = _make_scraper()
        page = _make_mock_page(price_text="$1,299.99")
        scraper._page = page

        result = asyncio.run(
            scraper._extract_price(page)
        )
        assert result == 1299.99


# ---------------------------------------------------------------------------
# Retry on page load failure tests
# ---------------------------------------------------------------------------
class TestRetryOnPageLoadFailure:
    def test_retries_on_http_error_then_succeeds(self):
        scraper = _make_scraper()

        # First call returns 500, second returns 200
        response_fail = AsyncMock()
        response_fail.status = 500

        response_ok = AsyncMock()
        response_ok.status = 200

        page = _make_mock_page()
        page.goto = AsyncMock(side_effect=[response_fail, response_ok])
        scraper._page = page

        # Should not raise
        asyncio.run(
            scraper._navigate_with_retry(
                page,
                "https://www.amazon.com/dp/B0BSHF7WHN",
            )
        )
        assert page.goto.call_count == 2

    def test_raises_after_max_retries_exhausted(self):
        scraper = _make_scraper()

        response_fail = AsyncMock()
        response_fail.status = 500

        page = _make_mock_page()
        page.goto = AsyncMock(return_value=response_fail)
        scraper._page = page

        with pytest.raises(ScraperError, match="HTTP 500"):
            asyncio.run(
                scraper._navigate_with_retry(
                    page,
                    "https://www.amazon.com/dp/B0BSHF7WHN",
                    max_retries=1,
                )
            )
        # 1 initial + 1 retry = 2 attempts
        assert page.goto.call_count == 2

    def test_retries_on_network_error(self):
        scraper = _make_scraper()

        response_ok = AsyncMock()
        response_ok.status = 200

        page = _make_mock_page()
        page.goto = AsyncMock(
            side_effect=[Exception("net::ERR_CONNECTION_RESET"), response_ok]
        )
        scraper._page = page

        asyncio.run(
            scraper._navigate_with_retry(
                page,
                "https://www.amazon.com/dp/B0BSHF7WHN",
            )
        )
        assert page.goto.call_count == 2

    def test_network_error_raises_after_all_retries(self):
        scraper = _make_scraper()

        page = _make_mock_page()
        page.goto = AsyncMock(
            side_effect=Exception("net::ERR_CONNECTION_RESET")
        )
        scraper._page = page

        with pytest.raises(ScraperError, match="Failed to load page"):
            asyncio.run(
                scraper._navigate_with_retry(
                    page,
                    "https://www.amazon.com/dp/B0BSHF7WHN",
                    max_retries=1,
                )
            )
        assert page.goto.call_count == 2

    def test_retries_on_error_page_then_succeeds(self):
        scraper = _make_scraper()

        response_ok = AsyncMock()
        response_ok.status = 200

        page = _make_mock_page()
        page.goto = AsyncMock(return_value=response_ok)

        # First call detects error page, second does not
        call_count = {"n": 0}

        async def mock_is_error(p):
            call_count["n"] += 1
            return call_count["n"] == 1  # error on first, ok on second

        scraper._is_error_page = mock_is_error
        scraper._page = page

        asyncio.run(
            scraper._navigate_with_retry(
                page,
                "https://www.amazon.com/dp/B0BSHF7WHN",
            )
        )
        assert page.goto.call_count == 2


# ---------------------------------------------------------------------------
# Error page detection tests
# ---------------------------------------------------------------------------
class TestErrorPageDetection:
    def test_detects_dog_page(self):
        scraper = _make_scraper()
        page = _make_mock_page(error_page_selector="img[alt='Dogs of Amazon']")
        scraper._page = page

        result = asyncio.run(
            scraper._is_error_page(page)
        )
        assert result is True

    def test_detects_error_page_element(self):
        scraper = _make_scraper()
        page = _make_mock_page(error_page_selector="#error-page")
        scraper._page = page

        result = asyncio.run(
            scraper._is_error_page(page)
        )
        assert result is True

    def test_detects_error_text_in_body(self):
        scraper = _make_scraper()
        page = _make_mock_page(body_text="Sorry, we just need to make sure you're not a robot. Please try again.")
        scraper._page = page

        result = asyncio.run(
            scraper._is_error_page(page)
        )
        assert result is True

    def test_normal_page_not_detected_as_error(self):
        scraper = _make_scraper()
        page = _make_mock_page(body_text="ASUS ROG Router - High performance WiFi 6E router")
        scraper._page = page

        result = asyncio.run(
            scraper._is_error_page(page)
        )
        assert result is False


# ---------------------------------------------------------------------------
# Full scrape integration (mocked browser, end-to-end logic)
# ---------------------------------------------------------------------------
class TestScrapeProduct:
    def test_successful_scrape_returns_product_data(self):
        scraper = _make_scraper()
        page = _make_mock_page(
            title_text="Test Router",
            price_text="$299.99",
        )
        scraper._page = page

        # Mock _navigate_with_retry to skip the actual navigation
        scraper._navigate_with_retry = AsyncMock()

        result = asyncio.run(
            scraper._scrape_product(
                "https://www.amazon.com/dp/B0BSHF7WHN", "B0BSHF7WHN"
            )
        )
        assert result.name == "Test Router"
        assert result.price == 299.99
        assert result.asin == "B0BSHF7WHN"

    def test_missing_title_returns_unknown_product(self):
        scraper = _make_scraper()
        page = _make_mock_page(title_text=None, price_text="$29.99")
        scraper._page = page
        scraper._navigate_with_retry = AsyncMock()

        result = asyncio.run(
            scraper._scrape_product(
                "https://www.amazon.com/dp/B0BSHF7WHN", "B0BSHF7WHN"
            )
        )
        assert result.name == "Unknown Product"

    def test_captcha_raises_scraper_error(self):
        scraper = _make_scraper()
        page = _make_mock_page(has_captcha=True)
        scraper._page = page
        scraper._navigate_with_retry = AsyncMock()

        with pytest.raises(ScraperError, match="captcha_detected"):
            asyncio.run(
                scraper._scrape_product(
                    "https://www.amazon.com/dp/B0BSHF7WHN", "B0BSHF7WHN"
                )
            )

    def test_signin_redirect_raises_cookie_expired(self):
        scraper = _make_scraper()
        page = _make_mock_page(is_signin=True)
        scraper._page = page
        scraper._navigate_with_retry = AsyncMock()

        with pytest.raises(ScraperError, match="cookie_expired"):
            asyncio.run(
                scraper._scrape_product(
                    "https://www.amazon.com/dp/B0BSHF7WHN", "B0BSHF7WHN"
                )
            )

    def test_error_page_raises_scraper_error(self):
        scraper = _make_scraper()
        page = _make_mock_page(
            error_page_selector="#error-page",
            title_text=None,
        )
        scraper._page = page
        scraper._navigate_with_retry = AsyncMock()

        with pytest.raises(ScraperError, match="error page"):
            asyncio.run(
                scraper._scrape_product(
                    "https://www.amazon.com/dp/B0BSHF7WHN", "B0BSHF7WHN"
                )
            )
