from contextlib import contextmanager
from unittest.mock import patch, MagicMock

import pytest
import requests


@contextmanager
def mock_all_scrapers(finder, **overrides):
    """Mock all manufacturer scrapers on a ManualFinder instance.

    By default every scraper returns []. Pass scraper name as kwarg to
    override, e.g. mock_all_scrapers(finder, _search_tplink=["url"]).
    Returns a dict of the mock objects keyed by scraper name.
    """
    scraper_names = [
        "_search_tplink", "_search_asus", "_search_samsung",
        "_search_apc", "_search_anker", "_search_generic_support",
    ]
    mocks = {}
    patches = []
    for name in scraper_names:
        ret = overrides.get(name, [])
        p = patch.object(finder, name, return_value=ret)
        mock_obj = p.start()
        mocks[name] = mock_obj
        patches.append(p)
    try:
        yield mocks
    finally:
        for p in patches:
            p.stop()

from homebox_tools.lib.manual_finder import ManualFinder, is_valid_pdf


class TestPdfValidation:
    def test_valid_pdf_magic_bytes(self):
        assert is_valid_pdf(b"%PDF-1.4 fake content here") is True

    def test_invalid_no_magic_bytes(self):
        assert is_valid_pdf(b"<html>not a pdf</html>") is False

    def test_empty_content(self):
        assert is_valid_pdf(b"") is False

    def test_too_short(self):
        assert is_valid_pdf(b"%PD") is False


class TestDedup:
    def test_detects_duplicates(self):
        finder = ManualFinder()
        content = b"%PDF-1.4 test content"
        assert finder._is_duplicate(content) is False  # first time
        assert finder._is_duplicate(content) is True   # duplicate

    def test_allows_unique(self):
        finder = ManualFinder()
        assert finder._is_duplicate(b"%PDF-1.4 content A") is False
        assert finder._is_duplicate(b"%PDF-1.4 content B") is False


class TestSizeLimits:
    def test_rejects_oversized_file(self):
        finder = ManualFinder()
        assert finder._check_size(21 * 1024 * 1024) is False

    def test_accepts_valid_size(self):
        finder = ManualFinder()
        assert finder._check_size(5 * 1024 * 1024) is True

    def test_rejects_when_aggregate_exceeded(self):
        finder = ManualFinder()
        finder._total_size = 45 * 1024 * 1024
        assert finder._check_aggregate(10 * 1024 * 1024) is False

    def test_accepts_within_aggregate(self):
        finder = ManualFinder()
        finder._total_size = 30 * 1024 * 1024
        assert finder._check_aggregate(10 * 1024 * 1024) is True


class TestGuessDomain:
    def test_simple_name(self):
        finder = ManualFinder()
        assert finder._guess_domain("ASUS") == "asus.com"

    def test_name_with_special_chars(self):
        finder = ManualFinder()
        assert finder._guess_domain("TP-Link") == "tplink.com"

    def test_empty_name(self):
        finder = ManualFinder()
        assert finder._guess_domain("") is None


class TestFindManuals:
    def test_empty_model_returns_empty(self):
        finder = ManualFinder()
        assert finder.find_manuals("") == []

    def test_none_model_returns_empty(self):
        finder = ManualFinder()
        assert finder.find_manuals(None) == []


class TestTPLinkSearch:
    def test_finds_document_ids_and_follows_redirects(self):
        finder = ManualFinder()
        support_html = '''
        <a href="/us/document/80903/">User Guide</a>
        <a href="/us/document/12345/">Quick Install Guide</a>
        '''
        support_resp = MagicMock()
        support_resp.ok = True
        support_resp.text = support_html

        head_resp_1 = MagicMock()
        head_resp_1.url = "https://static.tp-link.com/upload/manual/HS300_UG.pdf"
        head_resp_2 = MagicMock()
        head_resp_2.url = "https://static.tp-link.com/upload/manual/HS300_QIG.pdf"

        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.get.return_value = support_resp
            mock_requests.head.side_effect = [head_resp_1, head_resp_2]
            urls = finder._search_tplink("HS300")

        assert len(urls) == 2
        assert "HS300_UG.pdf" in urls[0]
        assert "HS300_QIG.pdf" in urls[1]

    def test_skips_non_pdf_redirects(self):
        finder = ManualFinder()
        support_resp = MagicMock()
        support_resp.ok = True
        support_resp.text = '<a href="/us/document/99999/">Datasheet</a>'

        head_resp = MagicMock()
        head_resp.url = "https://www.tp-link.com/us/some-page.html"

        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.get.return_value = support_resp
            mock_requests.head.return_value = head_resp
            urls = finder._search_tplink("HS300")

        assert urls == []

    def test_handles_support_page_not_found(self):
        finder = ManualFinder()
        resp = MagicMock()
        resp.ok = False

        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.get.return_value = resp
            urls = finder._search_tplink("NOMODEL")

        assert urls == []

    def test_manufacturer_routing_kasa(self):
        finder = ManualFinder()
        with mock_all_scrapers(finder, _search_tplink=["https://example.com/manual.pdf"]) as mocks:
            urls = finder._search_manufacturer("HS300", "Kasa")
        mocks["_search_tplink"].assert_called_once_with("HS300")
        assert "https://example.com/manual.pdf" in urls

    def test_manufacturer_routing_unknown_uses_generic(self):
        finder = ManualFinder()
        with mock_all_scrapers(finder) as mocks:
            urls = finder._search_manufacturer("X100", "UnknownBrand")
        mocks["_search_generic_support"].assert_called_once_with("X100", "UnknownBrand")
        assert urls == []


class TestASUSSearch:
    """Tests for ASUS manufacturer-direct manual scraper."""

    # Realistic __NUXT__ SSR fragment with manual entries
    _NUXT_HTML = '''
    <script>window.__NUXT__=(function(a,b){return {data:[{
    manualList:[
    {Id:"11@2@0@305@36@12@E23424_GT-AXE16000_UM_v2_0510.pdf",Version:"E23424",Title:"ASUS GT-AXE16000 user's manual in English",Description:a,FileSize:"8.05 MB",ReleaseDate:"2024\\u002F05\\u002F15",IsRelease:b,PosType:a,DownloadUrl:{Global:"\\u002Fpub\\u002FASUS\\u002Fwireless\\u002FGT-AXE16000\\u002FE23424_GT-AXE16000_UM_v2_0510.pdf",China:a},HardwareInfoList:a},
    {Id:"11@2@0@305@36@12@SA22333_GT-AXE16000_one-page_QSG_V3_WEB.pdf",Version:"SA22333",Title:"ASUS GT-AXE16000 QSG (Quick Start Guide) for English\\u002FSpanish",Description:a,FileSize:"1.29 MB",ReleaseDate:"2023\\u002F09\\u002F07",IsRelease:b,PosType:a,DownloadUrl:{Global:"\\u002Fpub\\u002FASUS\\u002Fwireless\\u002FGT-AXE16000\\u002FSA22333_GT-AXE16000_one-page_QSG_V3_WEB.pdf",China:a},HardwareInfoList:a},
    {Id:"11@2@0@305@36@12@U26180_CE_Safety_Notices.pdf",Version:"U26180",Title:"CE Safety Notice For Wireless",Description:a,FileSize:"912.27 KB",ReleaseDate:"2025\\u002F06\\u002F13",IsRelease:b,PosType:a,DownloadUrl:{Global:"\\u002Fpub\\u002FASUS\\u002Fwireless\\u002FU26180_CE_Safety_Notices.pdf",China:a},HardwareInfoList:a},
    {Id:"11@2@0@305@36@12@F22333_GT-AXE16000_QSG_French.pdf",Version:"F22333",Title:"ASUS GT-AXE16000 QSG (Quick Start Guide) for French",Description:a,FileSize:"1.26 MB",ReleaseDate:"2023\\u002F09\\u002F07",IsRelease:b,PosType:a,DownloadUrl:{Global:"\\u002Fpub\\u002FASUS\\u002Fwireless\\u002FGT-AXE16000\\u002FF22333_GT-AXE16000_QSG_French.pdf",China:a},HardwareInfoList:a}
    ]}]}}("",true))</script>
    '''

    def test_finds_manual_pdfs_from_nuxt_data(self):
        """Happy path: support page returns manual entries in __NUXT__ blob."""
        finder = ManualFinder()
        resp = MagicMock()
        resp.ok = True
        resp.text = self._NUXT_HTML

        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.get.return_value = resp
            urls = finder._search_asus("GT-AXE16000")

        # Should find the manuals (safety notice deprioritised)
        assert len(urls) >= 2
        # English user manual should be first (highest priority)
        assert "E23424_GT-AXE16000_UM_v2_0510.pdf" in urls[0]
        assert urls[0].startswith("https://dlcdnets.asus.com/pub/ASUS/")

    def test_prioritises_english_user_manual(self):
        """English user manual should sort before QSGs and safety notices."""
        finder = ManualFinder()
        resp = MagicMock()
        resp.ok = True
        resp.text = self._NUXT_HTML

        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.get.return_value = resp
            urls = finder._search_asus("GT-AXE16000")

        # First URL should be the English user manual
        assert "E23424" in urls[0]
        # Safety notice should be last
        assert "U26180" in urls[-1]

    def test_decodes_unicode_slashes(self):
        """\\u002F in Nuxt data should be decoded to /."""
        finder = ManualFinder()
        resp = MagicMock()
        resp.ok = True
        resp.text = self._NUXT_HTML

        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.get.return_value = resp
            urls = finder._search_asus("GT-AXE16000")

        # All URLs should have proper slashes, not unicode escapes
        for url in urls:
            assert "\\u002F" not in url
            assert "/pub/ASUS/" in url

    def test_handles_support_page_not_found(self):
        """Non-200 response returns empty list."""
        finder = ManualFinder()
        resp = MagicMock()
        resp.ok = False

        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.get.return_value = resp
            urls = finder._search_asus("NOMODEL")

        assert urls == []

    def test_handles_page_with_no_manual_data(self):
        """Page that returns 200 but has no manual entries in __NUXT__."""
        finder = ManualFinder()
        resp = MagicMock()
        resp.ok = True
        resp.text = "<html><body>No manuals here</body></html>"

        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.get.return_value = resp
            urls = finder._search_asus("GT-AXE16000")

        assert urls == []

    def test_handles_network_error(self):
        """Network exceptions return empty list."""
        finder = ManualFinder()
        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.get.side_effect = requests.ConnectionError("timeout")
            urls = finder._search_asus("GT-AXE16000")

        assert urls == []

    def test_limits_to_five_urls(self):
        """Should not return more than 5 PDF URLs."""
        finder = ManualFinder()
        # Build HTML with 8 manual entries
        entries = []
        for i in range(8):
            entries.append(
                f'Version:"V{i:04d}",Title:"Manual {i}",'
                f'Description:a,DownloadUrl:{{Global:"/pub/ASUS/doc{i}.pdf"}}'
            )
        html = "<script>__NUXT__=" + ",".join(entries) + "</script>"
        resp = MagicMock()
        resp.ok = True
        resp.text = html

        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.get.return_value = resp
            urls = finder._search_asus("SOMEMODEL")

        assert len(urls) == 5

    def test_deduplicates_by_path(self):
        """Same PDF path appearing multiple times should be deduped."""
        finder = ManualFinder()
        html = '''<script>__NUXT__=
        Version:"E001",Title:"Manual A",Description:a,DownloadUrl:{Global:"/pub/ASUS/same.pdf"}
        Version:"E002",Title:"Manual B",Description:a,DownloadUrl:{Global:"/pub/ASUS/same.pdf"}
        </script>'''
        resp = MagicMock()
        resp.ok = True
        resp.text = html

        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.get.return_value = resp
            urls = finder._search_asus("SOMEMODEL")

        assert len(urls) == 1

    def test_manufacturer_routing_asus(self):
        """'asus' manufacturer routes to _search_asus."""
        finder = ManualFinder()
        with mock_all_scrapers(finder, _search_asus=["https://dlcdnets.asus.com/pub/ASUS/manual.pdf"]) as mocks:
            urls = finder._search_manufacturer("GT-AXE16000", "ASUS")
        mocks["_search_asus"].assert_called_once_with("GT-AXE16000")
        assert "https://dlcdnets.asus.com/pub/ASUS/manual.pdf" in urls

    def test_manufacturer_routing_rog(self):
        """'rog' manufacturer routes to _search_asus."""
        finder = ManualFinder()
        with mock_all_scrapers(finder) as mocks:
            finder._search_manufacturer("STRIX-B550", "ROG")
        mocks["_search_asus"].assert_called_once_with("STRIX-B550")

    def test_uses_correct_support_url(self):
        """Verify the support URL is correctly formed."""
        finder = ManualFinder()
        resp = MagicMock()
        resp.ok = True
        resp.text = "<html></html>"

        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.get.return_value = resp
            finder._search_asus("GT-AXE16000")

        call_args = mock_requests.get.call_args
        url = call_args[0][0]
        assert url == "https://www.asus.com/supportonly/GT-AXE16000/helpdesk_manual/"

    def test_motherboard_model(self):
        """Test with a motherboard-style model (different product category in URL path)."""
        finder = ManualFinder()
        html = '''<script>__NUXT__=
        Version:"E16609",Title:"ROG STRIX B550-F GAMING User's Manual ( English Edition )",Description:a,DownloadUrl:{Global:"\\u002Fpub\\u002FASUS\\u002Fmb\\u002FSocketAM4\\u002FROG_STRIX_B550-F_GAMING\\u002FE16609_ROG_STRIX_B550-F_GAMING_UM_WEB.pdf"}
        </script>'''
        resp = MagicMock()
        resp.ok = True
        resp.text = html

        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.get.return_value = resp
            urls = finder._search_asus("ROG STRIX B550-F GAMING")

        assert len(urls) == 1
        assert "E16609_ROG_STRIX_B550-F_GAMING_UM_WEB.pdf" in urls[0]
        assert urls[0].startswith("https://dlcdnets.asus.com/pub/ASUS/mb/")


class TestArchiveOrgSearch:
    def test_finds_pdfs_from_archive(self):
        finder = ManualFinder()
        search_resp = MagicMock()
        search_resp.ok = True
        search_resp.json.return_value = {
            "response": {
                "docs": [
                    {"identifier": "hs300-manual", "title": "HS300 User Guide"},
                ]
            }
        }

        files_resp = MagicMock()
        files_resp.ok = True
        files_resp.json.return_value = {
            "result": [
                {"name": "HS300_User_Guide.pdf"},
                {"name": "cover.jpg"},
                {"name": "HS300_Quick_Start.pdf"},
            ]
        }

        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.get.side_effect = [search_resp, files_resp]
            urls = finder._search_archive_org("HS300", "Kasa")

        assert len(urls) == 2
        assert "archive.org/download/hs300-manual/HS300_User_Guide.pdf" in urls[0]
        assert "archive.org/download/hs300-manual/HS300_Quick_Start.pdf" in urls[1]

    def test_handles_no_results(self):
        finder = ManualFinder()
        resp = MagicMock()
        resp.ok = True
        resp.json.return_value = {"response": {"docs": []}}

        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.get.return_value = resp
            urls = finder._search_archive_org("NOMODEL")

        assert urls == []

    def test_handles_search_failure(self):
        finder = ManualFinder()
        resp = MagicMock()
        resp.ok = False

        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.get.return_value = resp
            urls = finder._search_archive_org("HS300")

        assert urls == []

    def test_handles_files_endpoint_failure(self):
        finder = ManualFinder()
        search_resp = MagicMock()
        search_resp.ok = True
        search_resp.json.return_value = {
            "response": {"docs": [{"identifier": "test-doc"}]}
        }
        files_resp = MagicMock()
        files_resp.ok = False

        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.get.side_effect = [search_resp, files_resp]
            urls = finder._search_archive_org("HS300")

        assert urls == []


class TestAnkerSearch:
    def test_finds_pdf_from_article_page(self):
        """Full happy path: listing page has article link, article page has S3 PDF."""
        finder = ManualFinder()
        listing_html = '''
        <a href="/article-description/A2331-Anker-323-Charger-33W-User-Manual">Manual</a>
        <a href="/article-description/A9999-Other-Product">Other</a>
        '''
        listing_resp = MagicMock()
        listing_resp.ok = True
        listing_resp.text = listing_html

        article_html = '''
        <div class="manual-download">
            <a href="https://salesforce-knowledge-download.s3.us-west-2.amazonaws.com/000011606/en_US/000011606.pdf">
                Download Manual
            </a>
        </div>
        '''
        article_resp = MagicMock()
        article_resp.ok = True
        article_resp.text = article_html

        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.get.side_effect = [listing_resp, article_resp]
            urls = finder._search_anker("A2331")

        assert len(urls) == 1
        assert "salesforce-knowledge-download.s3.us-west-2.amazonaws.com" in urls[0]
        assert urls[0].endswith(".pdf")

    def test_finds_multiple_pdfs_on_article_page(self):
        """Article page may contain multiple PDF links."""
        finder = ManualFinder()
        listing_html = '''
        <a href="/article-description/A1263-Anker-PowerCore-User-Manual">Manual</a>
        '''
        listing_resp = MagicMock()
        listing_resp.ok = True
        listing_resp.text = listing_html

        article_html = '''
        <a href="https://salesforce-knowledge-download.s3.us-west-2.amazonaws.com/000001/en_US/000001.pdf">UG</a>
        <a href="https://salesforce-knowledge-download.s3.us-west-2.amazonaws.com/000002/en_US/000002.pdf">QSG</a>
        '''
        article_resp = MagicMock()
        article_resp.ok = True
        article_resp.text = article_html

        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.get.side_effect = [listing_resp, article_resp]
            urls = finder._search_anker("A1263")

        assert len(urls) == 2

    def test_no_matching_article_returns_empty(self):
        """When listing page has no articles matching the model number."""
        finder = ManualFinder()
        listing_html = '''
        <a href="/article-description/A9999-Other-Product">Other</a>
        '''
        listing_resp = MagicMock()
        listing_resp.ok = True
        listing_resp.text = listing_html

        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.get.return_value = listing_resp
            urls = finder._search_anker("A2337")

        assert urls == []

    def test_listing_page_failure_returns_empty(self):
        finder = ManualFinder()
        resp = MagicMock()
        resp.ok = False

        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.get.return_value = resp
            urls = finder._search_anker("A2331")

        assert urls == []

    def test_article_page_failure_returns_empty(self):
        """When article page fails to load, skip it gracefully."""
        finder = ManualFinder()
        listing_html = '<a href="/article-description/A2331-Anker-Charger-Manual">M</a>'
        listing_resp = MagicMock()
        listing_resp.ok = True
        listing_resp.text = listing_html

        article_resp = MagicMock()
        article_resp.ok = False

        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.get.side_effect = [listing_resp, article_resp]
            urls = finder._search_anker("A2331")

        assert urls == []

    def test_network_exception_returns_empty(self):
        finder = ManualFinder()
        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.get.side_effect = requests.ConnectionError("timeout")
            urls = finder._search_anker("A2331")

        assert urls == []

    def test_case_insensitive_model_matching(self):
        """Model matching should be case-insensitive."""
        finder = ManualFinder()
        listing_html = '<a href="/article-description/a2331-anker-charger">M</a>'
        listing_resp = MagicMock()
        listing_resp.ok = True
        listing_resp.text = listing_html

        article_html = '''
        <a href="https://salesforce-knowledge-download.s3.us-west-2.amazonaws.com/000001/en_US/000001.pdf">M</a>
        '''
        article_resp = MagicMock()
        article_resp.ok = True
        article_resp.text = article_html

        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.get.side_effect = [listing_resp, article_resp]
            urls = finder._search_anker("A2331")

        assert len(urls) == 1

    def test_deduplicates_pdf_urls(self):
        """Same PDF URL appearing in multiple places should be deduped."""
        finder = ManualFinder()
        listing_html = '<a href="/article-description/A2331-Manual">M</a>'
        listing_resp = MagicMock()
        listing_resp.ok = True
        listing_resp.text = listing_html

        s3_url = "https://salesforce-knowledge-download.s3.us-west-2.amazonaws.com/000001/en_US/000001.pdf"
        article_html = f'<a href="{s3_url}">DL</a><a href="{s3_url}">DL2</a>'
        article_resp = MagicMock()
        article_resp.ok = True
        article_resp.text = article_html

        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.get.side_effect = [listing_resp, article_resp]
            urls = finder._search_anker("A2331")

        assert len(urls) == 1

    def test_manufacturer_routing_anker(self):
        finder = ManualFinder()
        with mock_all_scrapers(finder, _search_anker=["https://example.com/manual.pdf"]) as mocks:
            urls = finder._search_manufacturer("A2331", "Anker")
        mocks["_search_anker"].assert_called_once_with("A2331")
        assert "https://example.com/manual.pdf" in urls

    def test_manufacturer_routing_soundcore(self):
        finder = ManualFinder()
        with mock_all_scrapers(finder) as mocks:
            finder._search_manufacturer("A3939", "Soundcore")
        mocks["_search_anker"].assert_called_once_with("A3939")

    def test_manufacturer_routing_eufy(self):
        finder = ManualFinder()
        with mock_all_scrapers(finder) as mocks:
            finder._search_manufacturer("T8010", "Eufy")
        mocks["_search_anker"].assert_called_once_with("T8010")

    def test_full_url_in_listing_page(self):
        """Some listing pages may use full URLs instead of relative paths."""
        finder = ManualFinder()
        listing_html = '''
        <a href="https://service.anker.com/article-description/A2331-Anker-Charger">Manual</a>
        '''
        listing_resp = MagicMock()
        listing_resp.ok = True
        listing_resp.text = listing_html

        article_html = '''
        <a href="https://salesforce-knowledge-download.s3.us-west-2.amazonaws.com/000001/en_US/000001.pdf">DL</a>
        '''
        article_resp = MagicMock()
        article_resp.ok = True
        article_resp.text = article_html

        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.get.side_effect = [listing_resp, article_resp]
            urls = finder._search_anker("A2331")

        assert len(urls) == 1


class TestGenericSearch:
    def test_finds_pdfs_from_support_page(self):
        """When a support page returns 200 and has PDF links."""
        finder = ManualFinder()
        support_html = '''
        <a href="/downloads/X100_manual.pdf">User Manual</a>
        <a href="/downloads/X100_quickstart.pdf">Quick Start</a>
        <a href="/about.html">About</a>
        '''
        resp_ok = MagicMock()
        resp_ok.ok = True
        resp_ok.text = support_html

        resp_404 = MagicMock()
        resp_404.ok = False

        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            # First URL pattern succeeds, rest fail
            mock_requests.get.side_effect = [resp_ok, resp_404, resp_404, resp_404]
            urls = finder._search_generic_support("X100", "Acme")

        assert len(urls) == 2
        assert urls[0] == "https://acme.com/downloads/X100_manual.pdf"
        assert urls[1] == "https://acme.com/downloads/X100_quickstart.pdf"

    def test_handles_absolute_pdf_urls(self):
        """PDF links may be absolute URLs."""
        finder = ManualFinder()
        support_html = '''
        <a href="https://cdn.example.com/manuals/X100.pdf">Manual</a>
        '''
        resp_ok = MagicMock()
        resp_ok.ok = True
        resp_ok.text = support_html

        resp_404 = MagicMock()
        resp_404.ok = False

        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.get.side_effect = [resp_ok, resp_404, resp_404, resp_404]
            urls = finder._search_generic_support("X100", "Acme")

        assert len(urls) == 1
        assert urls[0] == "https://cdn.example.com/manuals/X100.pdf"

    def test_handles_protocol_relative_urls(self):
        """PDF links may start with //."""
        finder = ManualFinder()
        support_html = '<a href="//cdn.acme.com/docs/X100.pdf">Manual</a>'
        resp_ok = MagicMock()
        resp_ok.ok = True
        resp_ok.text = support_html

        resp_404 = MagicMock()
        resp_404.ok = False

        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.get.side_effect = [resp_ok, resp_404, resp_404, resp_404]
            urls = finder._search_generic_support("X100", "Acme")

        assert len(urls) == 1
        assert urls[0] == "https://cdn.acme.com/docs/X100.pdf"

    def test_all_patterns_fail_returns_empty(self):
        """When all URL patterns return non-200."""
        finder = ManualFinder()
        resp_404 = MagicMock()
        resp_404.ok = False

        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.get.return_value = resp_404
            urls = finder._search_generic_support("X100", "Acme")

        assert urls == []

    def test_network_errors_return_empty(self):
        """Network errors should be caught and return empty list."""
        finder = ManualFinder()
        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.get.side_effect = requests.ConnectionError("timeout")
            urls = finder._search_generic_support("X100", "Acme")

        assert urls == []

    def test_empty_manufacturer_returns_empty(self):
        """If manufacturer can't produce a domain, return empty."""
        finder = ManualFinder()
        urls = finder._search_generic_support("X100", "")
        assert urls == []

    def test_limits_to_five_pdfs(self):
        """Should not return more than 5 PDF URLs."""
        finder = ManualFinder()
        many_pdfs = "\n".join(
            f'<a href="/doc{i}.pdf">Doc {i}</a>' for i in range(10)
        )
        resp_ok = MagicMock()
        resp_ok.ok = True
        resp_ok.text = many_pdfs

        resp_404 = MagicMock()
        resp_404.ok = False

        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.get.side_effect = [resp_ok, resp_404, resp_404, resp_404]
            urls = finder._search_generic_support("X100", "Acme")

        assert len(urls) == 5

    def test_deduplicates_across_pages(self):
        """Same PDF found on multiple support pages should appear once."""
        finder = ManualFinder()
        html = '<a href="/manual.pdf">Manual</a>'
        resp_ok = MagicMock()
        resp_ok.ok = True
        resp_ok.text = html

        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.get.return_value = resp_ok
            urls = finder._search_generic_support("X100", "Acme")

        assert len(urls) == 1

    def test_pdf_with_query_string(self):
        """PDF links with query parameters should be captured."""
        finder = ManualFinder()
        support_html = '<a href="/docs/manual.pdf?v=2&lang=en">Manual</a>'
        resp_ok = MagicMock()
        resp_ok.ok = True
        resp_ok.text = support_html

        resp_404 = MagicMock()
        resp_404.ok = False

        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.get.side_effect = [resp_ok, resp_404, resp_404, resp_404]
            urls = finder._search_generic_support("X100", "Acme")

        assert len(urls) == 1
        assert "manual.pdf?v=2&lang=en" in urls[0]

    def test_tries_correct_url_patterns(self):
        """Verify all four URL patterns are attempted."""
        finder = ManualFinder()
        resp_404 = MagicMock()
        resp_404.ok = False

        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.get.return_value = resp_404
            finder._search_generic_support("X100", "Acme")

        calls = mock_requests.get.call_args_list
        urls_tried = [call[0][0] for call in calls]
        assert "https://acme.com/support/download/X100/" in urls_tried
        assert "https://acme.com/support/X100/" in urls_tried
        assert "https://acme.com/products/X100/support" in urls_tried
        assert "https://support.acme.com/X100/" in urls_tried

    def test_manufacturer_routing_uses_generic_fallback(self):
        """Unknown manufacturers should route through generic search."""
        finder = ManualFinder()
        with mock_all_scrapers(finder, _search_generic_support=["https://example.com/manual.pdf"]) as mocks:
            urls = finder._search_manufacturer("X100", "SomeUnknownBrand")
        mocks["_search_generic_support"].assert_called_once_with("X100", "SomeUnknownBrand")
        assert "https://example.com/manual.pdf" in urls

    def test_bare_filename_pdf_href(self):
        """PDF href with no leading slash should be made absolute."""
        finder = ManualFinder()
        support_html = '<a href="manual.pdf">Manual</a>'
        resp_ok = MagicMock()
        resp_ok.ok = True
        resp_ok.text = support_html

        resp_404 = MagicMock()
        resp_404.ok = False

        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.get.side_effect = [resp_ok, resp_404, resp_404, resp_404]
            urls = finder._search_generic_support("X100", "Acme")

        assert len(urls) == 1
        assert urls[0] == "https://acme.com/manual.pdf"


class TestSamsungSearch:
    """Tests for the Samsung manufacturer-direct scraper."""

    def _make_api_response(self, downloads):
        """Helper to create a mock Samsung API response."""
        resp = MagicMock()
        resp.ok = True
        resp.json.return_value = [{"downloads": downloads}]
        return resp

    def test_finds_english_user_manual_pdfs(self):
        """Happy path: API returns UserManual entries with download URLs."""
        finder = ManualFinder()
        downloads = {
            "UserManual": {
                "ENGLISH": [
                    {
                        "fileName": "e-Manual",
                        "downloadUrl": (
                            "https://org.downloadcenter.samsung.com/downloadfile/"
                            "ContentsFile.aspx?CDSite=US&CttFileID=10635797"
                            "&CDCttType=UM&ModelType=C&ModelName=QN65Q80CAFXZA"
                            "&VPath=UM/202507/manual.pdf"
                        ),
                    },
                    {
                        "fileName": "User Manual",
                        "downloadUrl": (
                            "https://org.downloadcenter.samsung.com/downloadfile/"
                            "ContentsFile.aspx?CDSite=US&CttFileID=11045388"
                            "&CDCttType=EM&ModelType=C&ModelName=QN65Q80CAFXZA"
                            "&VPath=EM/202511/user_manual.pdf"
                        ),
                    },
                ],
            },
        }
        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.get.return_value = self._make_api_response(downloads)
            urls = finder._search_samsung("QN65Q80CAFXZA")

        assert len(urls) == 2
        assert "CttFileID=10635797" in urls[0]
        assert "CttFileID=11045388" in urls[1]

    def test_deduplicates_by_cttfileid(self):
        """Same CttFileID in UserManual and manuals categories should appear once."""
        finder = ManualFinder()
        entry = {
            "fileName": "e-Manual",
            "downloadUrl": (
                "https://org.downloadcenter.samsung.com/downloadfile/"
                "ContentsFile.aspx?CDSite=US&CttFileID=10635797"
                "&CDCttType=UM&ModelType=C&ModelName=QN65Q80CAFXZA"
                "&VPath=UM/202507/manual.pdf"
            ),
        }
        downloads = {
            "UserManual": {"ENGLISH": [entry]},
            "manuals": {"ENGLISH": [entry]},
        }
        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.get.return_value = self._make_api_response(downloads)
            urls = finder._search_samsung("QN65Q80CAFXZA")

        assert len(urls) == 1

    def test_prioritises_user_manual_over_quick_start(self):
        """UserManual entries should appear before QuickStartGuide."""
        finder = ManualFinder()
        downloads = {
            "QuickStartGuide": {
                "ENGLISH": [
                    {
                        "fileName": "Quick Guide",
                        "downloadUrl": (
                            "https://org.downloadcenter.samsung.com/downloadfile/"
                            "ContentsFile.aspx?CDSite=US&CttFileID=9202495"
                            "&CDCttType=EM&VPath=quick_guide.pdf"
                        ),
                    },
                ],
            },
            "UserManual": {
                "ENGLISH": [
                    {
                        "fileName": "e-Manual",
                        "downloadUrl": (
                            "https://org.downloadcenter.samsung.com/downloadfile/"
                            "ContentsFile.aspx?CDSite=US&CttFileID=10635797"
                            "&CDCttType=UM&VPath=manual.pdf"
                        ),
                    },
                ],
            },
        }
        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.get.return_value = self._make_api_response(downloads)
            urls = finder._search_samsung("QN65Q80CAFXZA")

        assert len(urls) == 2
        # UserManual should come first due to priority ordering
        assert "CttFileID=10635797" in urls[0]
        assert "CttFileID=9202495" in urls[1]

    def test_includes_multi_language_manuals(self):
        """MULTI LANGUAGE manuals should be included as fallback."""
        finder = ManualFinder()
        downloads = {
            "UserManual": {
                "MULTI LANGUAGE": [
                    {
                        "fileName": "User Manual",
                        "downloadUrl": (
                            "https://org.downloadcenter.samsung.com/downloadfile/"
                            "ContentsFile.aspx?CDSite=US&CttFileID=9772128"
                            "&CDCttType=EM&VPath=multi_lang_manual.pdf"
                        ),
                    },
                ],
                "SPANISH": [
                    {
                        "fileName": "e-Manual",
                        "downloadUrl": (
                            "https://org.downloadcenter.samsung.com/downloadfile/"
                            "ContentsFile.aspx?CDSite=US&CttFileID=10635799"
                            "&CDCttType=UM&VPath=spanish_manual.pdf"
                        ),
                    },
                ],
            },
        }
        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.get.return_value = self._make_api_response(downloads)
            urls = finder._search_samsung("QN65Q80CAFXZA")

        # Should include MULTI LANGUAGE but not SPANISH
        assert len(urls) == 1
        assert "CttFileID=9772128" in urls[0]

    def test_skips_non_pdf_download_urls(self):
        """Entries without .pdf in the URL should be skipped."""
        finder = ManualFinder()
        downloads = {
            "UserManual": {
                "ENGLISH": [
                    {
                        "fileName": "Firmware",
                        "downloadUrl": (
                            "https://org.downloadcenter.samsung.com/downloadfile/"
                            "ContentsFile.aspx?CDSite=US&CttFileID=12345"
                            "&CDCttType=SW&VPath=SW/firmware.zip"
                        ),
                    },
                ],
            },
        }
        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.get.return_value = self._make_api_response(downloads)
            urls = finder._search_samsung("QN65Q80CAFXZA")

        assert urls == []

    def test_limits_to_five_urls(self):
        """Should not return more than 5 PDF URLs."""
        finder = ManualFinder()
        entries = [
            {
                "fileName": f"Manual {i}",
                "downloadUrl": (
                    f"https://org.downloadcenter.samsung.com/downloadfile/"
                    f"ContentsFile.aspx?CDSite=US&CttFileID={1000 + i}"
                    f"&CDCttType=UM&VPath=manual_{i}.pdf"
                ),
            }
            for i in range(8)
        ]
        downloads = {"UserManual": {"ENGLISH": entries}}
        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.get.return_value = self._make_api_response(downloads)
            urls = finder._search_samsung("QN65Q80CAFXZA")

        assert len(urls) == 5

    def test_api_returns_404(self):
        """When the Samsung API returns a non-200, return empty list."""
        finder = ManualFinder()
        resp = MagicMock()
        resp.ok = False

        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.get.return_value = resp
            urls = finder._search_samsung("NONEXISTENT")

        assert urls == []

    def test_api_returns_empty_list(self):
        """When the API returns an empty JSON array."""
        finder = ManualFinder()
        resp = MagicMock()
        resp.ok = True
        resp.json.return_value = []

        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.get.return_value = resp
            urls = finder._search_samsung("NOMODEL")

        assert urls == []

    def test_api_returns_no_downloads_key(self):
        """When the API response has no downloads section."""
        finder = ManualFinder()
        resp = MagicMock()
        resp.ok = True
        resp.json.return_value = [{"modelCode": "ABC", "modelName": "ABC"}]

        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.get.return_value = resp
            urls = finder._search_samsung("ABC")

        assert urls == []

    def test_network_exception_returns_empty(self):
        """Network errors should be caught and return empty list."""
        finder = ManualFinder()
        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.get.side_effect = requests.ConnectionError("timeout")
            urls = finder._search_samsung("QN65Q80CAFXZA")

        assert urls == []

    def test_json_parse_error_returns_empty(self):
        """If the API returns invalid JSON, fail gracefully."""
        finder = ManualFinder()
        resp = MagicMock()
        resp.ok = True
        resp.json.side_effect = ValueError("Invalid JSON")

        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.get.return_value = resp
            urls = finder._search_samsung("QN65Q80CAFXZA")

        assert urls == []

    def test_manufacturer_routing_samsung(self):
        """'samsung' manufacturer should route to _search_samsung."""
        finder = ManualFinder()
        with mock_all_scrapers(finder, _search_samsung=["https://org.downloadcenter.samsung.com/manual.pdf"]) as mocks:
            urls = finder._search_manufacturer("QN65Q80CAFXZA", "Samsung")
        mocks["_search_samsung"].assert_called_once_with("QN65Q80CAFXZA")
        assert "https://org.downloadcenter.samsung.com/manual.pdf" in urls

    def test_manufacturer_routing_galaxy(self):
        """'galaxy' brand name should route to _search_samsung."""
        finder = ManualFinder()
        with mock_all_scrapers(finder) as mocks:
            finder._search_manufacturer("SM-S918B", "Galaxy")
        mocks["_search_samsung"].assert_called_once_with("SM-S918B")

    def test_handles_dict_response(self):
        """Some Samsung API responses may return a dict instead of a list."""
        finder = ManualFinder()
        resp = MagicMock()
        resp.ok = True
        resp.json.return_value = {
            "downloads": {
                "UserManual": {
                    "ENGLISH": [
                        {
                            "fileName": "User Manual",
                            "downloadUrl": (
                                "https://org.downloadcenter.samsung.com/downloadfile/"
                                "ContentsFile.aspx?CDSite=US&CttFileID=99999"
                                "&CDCttType=UM&VPath=manual.pdf"
                            ),
                        },
                    ],
                },
            },
        }

        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.get.return_value = resp
            urls = finder._search_samsung("SM-S918B")

        assert len(urls) == 1
        assert "CttFileID=99999" in urls[0]

    def test_empty_downloads_returns_empty(self):
        """When downloads dict exists but has no categories with files."""
        finder = ManualFinder()
        downloads = {
            "UmaUserMannual": {"LandingPageUrl": {"Url": None}},
            "Legal": {},
            "FlashManual": {},
            "Driver": None,
            "Software": None,
            "Firmware": None,
        }
        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.get.return_value = self._make_api_response(downloads)
            urls = finder._search_samsung("QN65Q80CAFXZA")

        assert urls == []

    def test_entries_without_download_url_skipped(self):
        """Entries missing the downloadUrl field should be skipped."""
        finder = ManualFinder()
        downloads = {
            "UserManual": {
                "ENGLISH": [
                    {"fileName": "Manual", "fileSize": "1.00 MB"},
                    {
                        "fileName": "User Manual",
                        "downloadUrl": (
                            "https://org.downloadcenter.samsung.com/downloadfile/"
                            "ContentsFile.aspx?CDSite=US&CttFileID=55555"
                            "&CDCttType=UM&VPath=manual.pdf"
                        ),
                    },
                ],
            },
        }
        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.get.return_value = self._make_api_response(downloads)
            urls = finder._search_samsung("QN65Q80CAFXZA")

        assert len(urls) == 1
        assert "CttFileID=55555" in urls[0]


class TestAPCSearch:
    """Tests for APC (Schneider Electric) manufacturer-direct scraper."""

    def test_finds_datasheet_via_predictable_url(self):
        """Happy path: HEAD request to datasheet URL returns PDF content-type."""
        finder = ManualFinder()
        head_resp = MagicMock()
        head_resp.ok = True
        head_resp.headers = {"content-type": "application/pdf;charset=UTF-8"}

        # Product page blocked (typical Akamai response)
        product_resp = MagicMock()
        product_resp.ok = False

        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.head.return_value = head_resp
            mock_requests.get.return_value = product_resp
            urls = finder._search_apc("BE600M1")

        assert len(urls) == 1
        assert "BE600M1_DATASHEET" in urls[0]
        assert "download.schneider-electric.com" in urls[0]
        assert "p_enDocType=Product+Data+Sheet" in urls[0]

    def test_model_uppercased_in_url(self):
        """Model number should be uppercased in the download URL."""
        finder = ManualFinder()
        head_resp = MagicMock()
        head_resp.ok = True
        head_resp.headers = {"content-type": "application/pdf;charset=UTF-8"}

        product_resp = MagicMock()
        product_resp.ok = False

        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.head.return_value = head_resp
            mock_requests.get.return_value = product_resp
            urls = finder._search_apc("be600m1")

        assert len(urls) == 1
        assert "BE600M1_DATASHEET" in urls[0]

    def test_datasheet_not_found_returns_empty(self):
        """When datasheet HEAD returns non-200, and product page is blocked."""
        finder = ManualFinder()
        head_resp = MagicMock()
        head_resp.ok = False
        head_resp.headers = {}

        product_resp = MagicMock()
        product_resp.ok = False

        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.head.return_value = head_resp
            mock_requests.get.return_value = product_resp
            urls = finder._search_apc("NONEXISTENT")

        assert urls == []

    def test_datasheet_non_pdf_content_type_skipped(self):
        """When HEAD returns 200 but content-type is not PDF (e.g., ZIP)."""
        finder = ManualFinder()
        head_resp = MagicMock()
        head_resp.ok = True
        head_resp.headers = {"content-type": "application/zip;charset=UTF-8"}

        product_resp = MagicMock()
        product_resp.ok = False

        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.head.return_value = head_resp
            mock_requests.get.return_value = product_resp
            urls = finder._search_apc("BE600M1")

        assert urls == []

    def test_scrapes_product_page_for_cdn_urls(self):
        """When product page is accessible, extract download CDN URLs."""
        finder = ManualFinder()

        # Datasheet HEAD fails
        datasheet_head = MagicMock()
        datasheet_head.ok = False
        datasheet_head.headers = {}

        # Product page returns HTML with CDN download link
        product_html = '''
        <html>
        <a href="https://download.schneider-electric.com/files?p_Doc_Ref=SPD_AHUG-9XB6SU_EN&p_enDocType=User+guide">
            User Guide
        </a>
        </html>
        '''
        product_resp = MagicMock()
        product_resp.ok = True
        product_resp.text = product_html

        # HEAD check on CDN URL confirms PDF
        cdn_head = MagicMock()
        cdn_head.ok = True
        cdn_head.headers = {"content-type": "application/pdf;charset=UTF-8"}

        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.head.side_effect = [datasheet_head, cdn_head]
            mock_requests.get.return_value = product_resp
            urls = finder._search_apc("BE600M1")

        assert len(urls) == 1
        assert "SPD_AHUG-9XB6SU_EN" in urls[0]

    def test_scrapes_product_page_for_spd_refs(self):
        """When product page has SPD_ references, construct download URLs."""
        finder = ManualFinder()

        # Datasheet HEAD succeeds
        datasheet_head = MagicMock()
        datasheet_head.ok = True
        datasheet_head.headers = {"content-type": "application/pdf;charset=UTF-8"}

        # Product page has SPD_ reference in text
        product_html = '''
        <html>
        <div data-doc="SPD_AHUG-AJTDE9_EN">User Manual</div>
        </html>
        '''
        product_resp = MagicMock()
        product_resp.ok = True
        product_resp.text = product_html

        # HEAD check on SPD ref confirms PDF
        spd_head = MagicMock()
        spd_head.ok = True
        spd_head.headers = {"content-type": "application/pdf;charset=UTF-8"}

        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.head.side_effect = [datasheet_head, spd_head]
            mock_requests.get.return_value = product_resp
            urls = finder._search_apc("BR1500MS")

        assert len(urls) == 2
        assert "BR1500MS_DATASHEET" in urls[0]
        assert "SPD_AHUG-AJTDE9_EN" in urls[1]

    def test_skips_image_spd_refs(self):
        """SPD refs for images/thumbnails (Benefit, CENZ-) should be skipped."""
        finder = ManualFinder()

        # Datasheet fails
        datasheet_head = MagicMock()
        datasheet_head.ok = False
        datasheet_head.headers = {}

        # Product page has only image-related SPD refs
        product_html = '''
        <html>
        <img src="https://download.schneider-electric.com/files?p_Doc_Ref=SPD_CENZ-AV3MSY_A_H&p_File_Type=rendition_1500_jpg">
        <div data-doc="BE600M1_Benefit">Benefit</div>
        </html>
        '''
        product_resp = MagicMock()
        product_resp.ok = True
        product_resp.text = product_html

        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.head.return_value = datasheet_head
            mock_requests.get.return_value = product_resp
            urls = finder._search_apc("BE600M1")

        assert urls == []

    def test_product_page_blocked_still_returns_datasheet(self):
        """When se.com blocks the request (403), still return the datasheet."""
        finder = ManualFinder()

        head_resp = MagicMock()
        head_resp.ok = True
        head_resp.headers = {"content-type": "application/pdf;charset=UTF-8"}

        # Simulate Akamai 403 block
        product_resp = MagicMock()
        product_resp.ok = False
        product_resp.status_code = 403

        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.head.return_value = head_resp
            mock_requests.get.return_value = product_resp
            urls = finder._search_apc("SMT1500RM2UC")

        assert len(urls) == 1
        assert "SMT1500RM2UC_DATASHEET" in urls[0]

    def test_network_exception_returns_empty(self):
        """Network errors should be caught and return empty list."""
        finder = ManualFinder()
        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.head.side_effect = requests.ConnectionError("timeout")
            mock_requests.get.side_effect = requests.ConnectionError("timeout")
            urls = finder._search_apc("BE600M1")

        assert urls == []

    def test_limits_to_five_urls(self):
        """Should not return more than 5 PDF URLs."""
        finder = ManualFinder()

        # Datasheet succeeds
        datasheet_head = MagicMock()
        datasheet_head.ok = True
        datasheet_head.headers = {"content-type": "application/pdf;charset=UTF-8"}

        # Product page has many SPD refs
        spd_refs = " ".join(f"SPD_DOC-{i:04d}_EN" for i in range(10))
        product_html = f"<html>{spd_refs}</html>"
        product_resp = MagicMock()
        product_resp.ok = True
        product_resp.text = product_html

        # All HEAD checks return PDF
        spd_head = MagicMock()
        spd_head.ok = True
        spd_head.headers = {"content-type": "application/pdf;charset=UTF-8"}

        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.head.side_effect = [datasheet_head] + [spd_head] * 10
            mock_requests.get.return_value = product_resp
            urls = finder._search_apc("BE600M1")

        assert len(urls) <= 5

    def test_manufacturer_routing_apc(self):
        """'apc' manufacturer should route to _search_apc."""
        finder = ManualFinder()
        with mock_all_scrapers(finder, _search_apc=["https://download.schneider-electric.com/files?p_Doc_Ref=BE600M1_DATASHEET"]) as mocks:
            urls = finder._search_manufacturer("BE600M1", "APC")
        mocks["_search_apc"].assert_called_once_with("BE600M1")
        assert "https://download.schneider-electric.com/files?p_Doc_Ref=BE600M1_DATASHEET" in urls

    def test_manufacturer_routing_schneider(self):
        """'schneider' manufacturer should route to _search_apc."""
        finder = ManualFinder()
        with mock_all_scrapers(finder) as mocks:
            finder._search_manufacturer("SMT1500", "Schneider")
        mocks["_search_apc"].assert_called_once_with("SMT1500")

    def test_manufacturer_routing_schneider_electric(self):
        """'schneider electric' manufacturer should route to _search_apc."""
        finder = ManualFinder()
        with mock_all_scrapers(finder) as mocks:
            finder._search_manufacturer("AP9630", "Schneider Electric")
        mocks["_search_apc"].assert_called_once_with("AP9630")

    def test_deduplicates_urls(self):
        """Same URL found via datasheet and product page should appear once."""
        finder = ManualFinder()

        datasheet_url = (
            "https://download.schneider-electric.com/files?"
            "p_Doc_Ref=BE600M1_DATASHEET"
            "&p_enDocType=Product+Data+Sheet"
            "&p_File_Name=BE600M1_DATASHEET_WW_en-GB.pdf"
        )

        # Datasheet HEAD succeeds
        datasheet_head = MagicMock()
        datasheet_head.ok = True
        datasheet_head.headers = {"content-type": "application/pdf;charset=UTF-8"}

        # Product page contains same datasheet URL
        product_html = f'<a href="{datasheet_url}">Datasheet</a>'
        product_resp = MagicMock()
        product_resp.ok = True
        product_resp.text = product_html

        cdn_head = MagicMock()
        cdn_head.ok = True
        cdn_head.headers = {"content-type": "application/pdf;charset=UTF-8"}

        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.head.side_effect = [datasheet_head, cdn_head]
            mock_requests.get.return_value = product_resp
            urls = finder._search_apc("BE600M1")

        # The datasheet URL is already in pdf_urls, so the CDN URL check
        # should find it's a duplicate and skip it
        assert len(urls) == 1

    def test_head_timeout_on_datasheet_falls_through(self):
        """If HEAD request times out, skip datasheet and try product page."""
        finder = ManualFinder()

        product_resp = MagicMock()
        product_resp.ok = False

        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.head.side_effect = requests.Timeout("timed out")
            mock_requests.get.return_value = product_resp
            urls = finder._search_apc("BE600M1")

        assert urls == []

    def test_uses_correct_product_page_url(self):
        """Verify the se.com product page URL is correctly formed."""
        finder = ManualFinder()

        head_resp = MagicMock()
        head_resp.ok = False
        head_resp.headers = {}

        product_resp = MagicMock()
        product_resp.ok = False

        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.head.return_value = head_resp
            mock_requests.get.return_value = product_resp
            finder._search_apc("BE600M1")

        get_call = mock_requests.get.call_args
        assert get_call[0][0] == "https://www.se.com/us/en/product/BE600M1/"

    def test_spd_head_failure_skips_ref(self):
        """When HEAD check on an SPD ref fails, skip that ref gracefully."""
        finder = ManualFinder()

        # Datasheet HEAD fails
        datasheet_head = MagicMock()
        datasheet_head.ok = False
        datasheet_head.headers = {}

        # Product page has SPD ref
        product_html = '<html><div>SPD_AHUG-9XB6SU_EN</div></html>'
        product_resp = MagicMock()
        product_resp.ok = True
        product_resp.text = product_html

        # HEAD check on SPD ref returns non-PDF (e.g., ZIP)
        spd_head = MagicMock()
        spd_head.ok = True
        spd_head.headers = {"content-type": "application/zip;charset=UTF-8"}

        with patch("homebox_tools.lib.manual_finder.requests") as mock_requests:
            mock_requests.head.side_effect = [datasheet_head, spd_head]
            mock_requests.get.return_value = product_resp
            urls = finder._search_apc("BE600M1")

        assert urls == []


class TestTierPriority:
    """Verify tiers are tried in order and DDG is skipped when enough results found."""

    def test_skips_ddg_when_manufacturer_finds_enough(self):
        finder = ManualFinder()
        fake_urls = [f"https://example.com/manual{i}.pdf" for i in range(5)]

        with patch.object(finder, "_search_manufacturer", return_value=fake_urls) as mfr_mock, \
             patch.object(finder, "_search_archive_org", return_value=[]) as archive_mock, \
             patch.object(finder, "_search_ddg") as ddg_mock, \
             patch.object(finder, "_download_pdf", return_value=None):
            finder.find_manuals("HS300", "Kasa")

        mfr_mock.assert_called_once()
        archive_mock.assert_called_once()
        ddg_mock.assert_not_called()

    def test_falls_through_to_ddg_when_few_results(self):
        finder = ManualFinder()

        with patch.object(finder, "_search_manufacturer", return_value=[]) as mfr_mock, \
             patch.object(finder, "_search_archive_org", return_value=[]) as archive_mock, \
             patch.object(finder, "_search_ddg", return_value=[]) as ddg_mock, \
             patch.object(finder, "_download_pdf", return_value=None):
            finder.find_manuals("HS300", "Kasa")

        mfr_mock.assert_called_once()
        archive_mock.assert_called_once()
        assert ddg_mock.call_count >= 2  # ManualsLib + general PDF search

    def test_no_manufacturer_tries_all_scrapers(self):
        """When no manufacturer is given, all scrapers are tried organically."""
        finder = ManualFinder()

        with patch.object(finder, "_search_all_manufacturers", return_value=[]) as all_mock, \
             patch.object(finder, "_search_archive_org", return_value=[]) as archive_mock, \
             patch.object(finder, "_search_ddg", return_value=[]) as ddg_mock, \
             patch.object(finder, "_download_pdf", return_value=None):
            finder.find_manuals("HS300")

        all_mock.assert_called_once_with("HS300")
        archive_mock.assert_called_once()

    def test_manufacturer_tries_all_scrapers_not_just_hinted(self):
        """Even with a manufacturer hint, non-hinted scrapers are tried."""
        finder = ManualFinder()

        with patch.object(finder, "_search_tplink", return_value=[]) as tp_mock, \
             patch.object(finder, "_search_asus", return_value=["https://asus.com/manual.pdf"]) as asus_mock, \
             patch.object(finder, "_search_samsung", return_value=[]) as sam_mock, \
             patch.object(finder, "_search_apc", return_value=[]) as apc_mock, \
             patch.object(finder, "_search_anker", return_value=[]) as anker_mock, \
             patch.object(finder, "_search_generic_support", return_value=[]):
            urls = finder._search_manufacturer("HS300", "Kasa")

        tp_mock.assert_called_once()  # hinted, tried first
        asus_mock.assert_called_once()  # tried second, found result
        assert len(urls) == 1

    def test_manufacturer_stops_at_max_manuals(self):
        """Stops trying scrapers once MAX_MANUALS URLs are found."""
        finder = ManualFinder()
        fake_urls = [f"https://example.com/m{i}.pdf" for i in range(5)]

        with patch.object(finder, "_search_tplink", return_value=fake_urls), \
             patch.object(finder, "_search_asus") as asus_mock, \
             patch.object(finder, "_search_samsung") as sam_mock:
            urls = finder._search_manufacturer("HS300", "Kasa")

        assert len(urls) == 5
        asus_mock.assert_not_called()  # didn't need to try
        sam_mock.assert_not_called()
