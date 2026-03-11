"""Best-effort PDF manual discovery via multiple sources."""

import hashlib
import re
import tempfile
from pathlib import Path
from urllib.parse import unquote

import requests

from homebox_tools.lib.models import ManualInfo

MAX_FILE_SIZE = 20 * 1024 * 1024       # 20MB per file
MAX_AGGREGATE_SIZE = 50 * 1024 * 1024   # 50MB total
MAX_MANUALS = 5
DOWNLOAD_TIMEOUT = 30

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Manufacturer-specific support page scrapers (frozenset for use as dict keys)
_TPLINK_BRANDS = frozenset({"tp-link", "tplink", "kasa", "tapo"})
_ASUS_BRANDS = frozenset({"asus", "rog"})
_SAMSUNG_BRANDS = frozenset({"samsung", "galaxy"})
_APC_BRANDS = frozenset({"apc", "schneider", "schneider electric"})

# Samsung US support API — returns JSON with download URLs for a model code.
# Response is a list with one dict containing a 'downloads' key whose value
# maps category -> language -> list of file entries with 'downloadUrl'.
_SAMSUNG_API_URL = "https://www.samsung.com/us/api/support/product/detail/{model}.json"
_ANKER_BRANDS = frozenset({"anker", "soundcore", "eufy", "nebula"})

# Anker hosts manuals on Salesforce Knowledge S3 bucket, linked from
# service.anker.com article pages.
_ANKER_MANUALS_URL = (
    "https://service.anker.com/recommended"
    "?secondType=Manuals&type=DownLoad"
)
_ANKER_S3_PDF_RE = re.compile(
    r'https://salesforce-knowledge-download\.s3[^"\'<>\s]+\.pdf',
    re.IGNORECASE,
)


def is_valid_pdf(content: bytes) -> bool:
    return len(content) > 4 and content[:5] == b"%PDF-"


class ManualFinder:
    def __init__(self):
        self._seen_hashes: set[str] = set()
        self._total_size = 0

    def _is_duplicate(self, content: bytes) -> bool:
        h = hashlib.sha256(content).hexdigest()
        if h in self._seen_hashes:
            return True
        self._seen_hashes.add(h)
        return False

    def _check_size(self, size: int) -> bool:
        return size <= MAX_FILE_SIZE

    def _check_aggregate(self, size: int) -> bool:
        return (self._total_size + size) <= MAX_AGGREGATE_SIZE

    def find_manuals(self, model: str, manufacturer: str | None = None) -> list[ManualInfo]:
        if not model:
            return []

        pdf_urls: list[str] = []

        # Tier 0: Manufacturer direct (no rate-limit risk)
        # When manufacturer is known, use brand hints for speed.
        # When unknown, try all scrapers — failed lookups are cheap 404s.
        if manufacturer:
            pdf_urls.extend(self._search_manufacturer(model, manufacturer))
        else:
            pdf_urls.extend(self._search_all_manufacturers(model))

        # Tier 1: Internet Archive manuals collection (free, no API key)
        pdf_urls.extend(self._search_archive_org(model, manufacturer))

        # Tier 2: DuckDuckGo (ManualsLib + general PDF search)
        if len(pdf_urls) < MAX_MANUALS:
            query = f'site:manualslib.com "{model}" user manual'
            pdf_urls.extend(self._search_ddg(query))

        if len(pdf_urls) < MAX_MANUALS:
            query = f'"{model}" filetype:pdf user manual'
            pdf_urls.extend(self._search_ddg(query))

        if len(pdf_urls) < MAX_MANUALS and manufacturer:
            mfr_domain = self._guess_domain(manufacturer)
            if mfr_domain:
                query = f'site:{mfr_domain} "{model}" filetype:pdf'
                pdf_urls.extend(self._search_ddg(query))

        # Deduplicate URLs
        seen_urls: set[str] = set()
        unique_urls: list[str] = []
        for url in pdf_urls:
            if url not in seen_urls:
                seen_urls.add(url)
                unique_urls.append(url)

        # Download up to MAX_MANUALS
        manuals: list[ManualInfo] = []
        for url in unique_urls[:MAX_MANUALS * 2]:
            if len(manuals) >= MAX_MANUALS:
                break
            manual = self._download_pdf(url, model)
            if manual:
                manuals.append(manual)

        return manuals

    # --- Tier 0: Manufacturer direct ---
    #
    # Rather than maintaining a brand→scraper mapping, we try ALL scrapers
    # against the model number. Each scraper returns [] on 404/failure, so
    # the cost of a miss is one fast HTTP request. Known-brand routing is
    # used only as an optimisation to try the most likely scraper first.

    def _search_manufacturer(self, model: str, manufacturer: str) -> list[str]:
        mfr = manufacturer.lower().strip()

        # All available scrapers — each returns [] on failure
        all_scrapers = [
            self._search_tplink,
            self._search_asus,
            self._search_samsung,
            self._search_apc,
            self._search_anker,
        ]

        # Brand hint: try the most likely scraper first for speed
        _BRAND_HINTS: dict[frozenset[str], callable] = {
            _TPLINK_BRANDS: self._search_tplink,
            _ASUS_BRANDS: self._search_asus,
            _SAMSUNG_BRANDS: self._search_samsung,
            _APC_BRANDS: self._search_apc,
            _ANKER_BRANDS: self._search_anker,
        }

        # Find the hinted scraper (if any) and try it first
        hinted = None
        for brands, scraper in _BRAND_HINTS.items():
            if mfr in brands:
                hinted = scraper
                break

        pdf_urls: list[str] = []

        # Try hinted scraper first
        if hinted:
            pdf_urls.extend(hinted(model))
            if len(pdf_urls) >= MAX_MANUALS:
                return pdf_urls

        # Try remaining scrapers (skip the one we already tried)
        for scraper in all_scrapers:
            if scraper is hinted:
                continue
            pdf_urls.extend(scraper(model))
            if len(pdf_urls) >= MAX_MANUALS:
                return pdf_urls

        # Generic URL-pattern fallback
        pdf_urls.extend(self._search_generic_support(model, manufacturer))
        return pdf_urls

    def _search_all_manufacturers(self, model: str) -> list[str]:
        """Try all manufacturer scrapers without brand hints.

        Used when no manufacturer is known — each scraper returns [] on
        failure so the cost is just a few fast HTTP requests.
        """
        pdf_urls: list[str] = []
        for scraper in [
            self._search_tplink,
            self._search_asus,
            self._search_samsung,
            self._search_apc,
            self._search_anker,
        ]:
            pdf_urls.extend(scraper(model))
            if len(pdf_urls) >= MAX_MANUALS:
                return pdf_urls
        return pdf_urls

    def _search_tplink(self, model: str) -> list[str]:
        """Scrape TP-Link support page for document download links.

        TP-Link's /us/document/{id}/ endpoints 302-redirect to the actual PDF
        hosted on static.tp-link.com.
        """
        try:
            resp = requests.get(
                f"https://www.tp-link.com/us/support/download/{model}/",
                headers={"User-Agent": _USER_AGENT},
                timeout=15,
            )
            if not resp.ok:
                return []
            doc_ids = re.findall(r'/us/document/(\d+)/', resp.text)
            pdf_urls = []
            for doc_id in doc_ids[:5]:
                try:
                    r = requests.head(
                        f"https://www.tp-link.com/us/document/{doc_id}/",
                        allow_redirects=True,
                        headers={"User-Agent": _USER_AGENT},
                        timeout=10,
                    )
                    if r.url.lower().endswith(".pdf"):
                        pdf_urls.append(r.url)
                except Exception:
                    continue
            return pdf_urls
        except Exception:
            return []

    def _search_asus(self, model: str) -> list[str]:
        """Scrape ASUS support page for manual PDF download links.

        ASUS serves manual data via Nuxt SSR payloads embedded in the HTML of
        their ``/supportonly/{model}/helpdesk_manual/`` pages.  Each manual
        entry in the ``__NUXT__`` blob contains a ``Version``, ``Title``, and
        ``DownloadUrl.Global`` path that resolves against the ASUS CDN at
        ``https://dlcdnets.asus.com``.

        We extract all manual entries, prioritise English user-manuals over
        quick-start guides and safety notices, and return up to 5 PDF URLs.
        Returns an empty list on any failure (network, parsing, etc.).
        """
        _ASUS_CDN = "https://dlcdnets.asus.com"
        _ASUS_SUPPORT_URL = (
            "https://www.asus.com/supportonly/{model}/helpdesk_manual/"
        )
        # Regex to pull structured manual entries from the __NUXT__ SSR blob.
        # Matches: Version:"...",Title:"...",...DownloadUrl:{Global:"..."}
        _NUXT_MANUAL_RE = re.compile(
            r'Version:"(?P<version>[^"]+)"'
            r',Title:"(?P<title>[^"]+)"'
            r'.*?DownloadUrl:\{Global:"(?P<path>[^"]+)"',
        )

        try:
            resp = requests.get(
                _ASUS_SUPPORT_URL.format(model=model),
                headers={"User-Agent": _USER_AGENT},
                timeout=15,
                allow_redirects=True,
            )
            if not resp.ok:
                return []

            matches = _NUXT_MANUAL_RE.finditer(resp.text)
            # Collect (title, url) tuples
            entries: list[tuple[str, str]] = []
            seen_paths: set[str] = set()
            for m in matches:
                raw_path = m.group("path")
                # Nuxt encodes slashes as \u002F
                path = raw_path.replace("\\u002F", "/")
                if path in seen_paths:
                    continue
                seen_paths.add(path)
                title = m.group("title")
                url = f"{_ASUS_CDN}{path}"
                entries.append((title, url))

            if not entries:
                return []

            # Prioritise: English user manuals first, then English QSGs,
            # then other manuals, filtering out safety notices.
            def _sort_key(entry: tuple[str, str]) -> tuple[int, str]:
                title_lower = entry[0].lower()
                # Deprioritise safety notices
                if "safety" in title_lower:
                    return (90, title_lower)
                # English user manuals are highest priority
                is_english = "english" in title_lower or title_lower.startswith("asus ")
                is_user_manual = "user" in title_lower or "manual" in title_lower
                is_qsg = "qsg" in title_lower or "quick start" in title_lower
                if is_english and is_user_manual:
                    return (0, title_lower)
                if is_user_manual:
                    return (10, title_lower)
                if is_english and is_qsg:
                    return (20, title_lower)
                if is_qsg:
                    return (30, title_lower)
                if is_english:
                    return (40, title_lower)
                return (50, title_lower)

            entries.sort(key=_sort_key)
            return [url for _, url in entries[:5]]
        except Exception:
            return []

    def _search_samsung(self, model: str) -> list[str]:
        """Query Samsung US support API for PDF manual download URLs.

        Samsung exposes a public JSON API at
        /us/api/support/product/detail/{model}.json that returns product
        metadata including a ``downloads`` dict. Each category (UserManual,
        QuickStartGuide, etc.) maps language names to lists of file entries.
        We collect English PDF download URLs, deduplicating by CttFileID and
        prioritising UserManual entries over QuickStartGuide entries.
        """
        try:
            resp = requests.get(
                _SAMSUNG_API_URL.format(model=model),
                headers={"User-Agent": _USER_AGENT},
                timeout=15,
            )
            if not resp.ok:
                return []

            data = resp.json()
            # Response is a JSON array with one element
            if isinstance(data, list) and len(data) > 0:
                item = data[0]
            elif isinstance(data, dict):
                item = data
            else:
                return []

            downloads = item.get("downloads")
            if not isinstance(downloads, dict):
                return []

            # Collect URLs from prioritised categories, deduplicating by
            # CttFileID so the same manual isn't returned twice (the API
            # duplicates entries between UserManual and manuals categories).
            seen_file_ids: set[str] = set()
            pdf_urls: list[str] = []

            # Process categories in priority order
            priority_categories = ["UserManual", "QuickStartGuide"]
            for category in priority_categories + list(downloads.keys()):
                content = downloads.get(category)
                if not isinstance(content, dict):
                    continue
                # Prefer English, but accept MULTI LANGUAGE as fallback
                for lang_key in ["ENGLISH", "MULTI LANGUAGE"]:
                    items = content.get(lang_key)
                    if not isinstance(items, list):
                        continue
                    for entry in items:
                        if not isinstance(entry, dict):
                            continue
                        url = entry.get("downloadUrl", "")
                        if not url or ".pdf" not in url.lower():
                            continue
                        # Extract CttFileID for deduplication
                        file_id_match = re.search(
                            r"CttFileID=(\d+)", url
                        )
                        if file_id_match:
                            fid = file_id_match.group(1)
                            if fid in seen_file_ids:
                                continue
                            seen_file_ids.add(fid)
                        pdf_urls.append(url)
                        if len(pdf_urls) >= 5:
                            return pdf_urls

            return pdf_urls
        except Exception:
            return []

    def _search_apc(self, model: str) -> list[str]:
        """Find PDF documents from APC (Schneider Electric) download portal.

        APC products are now part of Schneider Electric.  Their main site
        (se.com) is heavily JavaScript-rendered and protected by Akamai bot
        detection, but the download CDN at download.schneider-electric.com
        serves files directly with predictable URL patterns.

        Strategy:
        1. Try the product data sheet PDF via the predictable URL pattern
           ``{model}_DATASHEET`` on download.schneider-electric.com.
        2. Fetch the se.com product page (which may be blocked by bot
           protection) and scrape for ``download.schneider-electric.com``
           PDF URLs or ``SPD_`` document references.
        3. For any discovered SPD_ refs, construct direct download URLs.

        Returns an empty list on any failure -- purely best-effort.
        """
        _APC_DOWNLOAD_BASE = "https://download.schneider-electric.com/files"

        pdf_urls: list[str] = []

        # Step 1: Try the predictable product data sheet URL.
        # Pattern: {MODEL}_DATASHEET with filename {MODEL}_DATASHEET_WW_en-GB.pdf
        model_upper = model.upper()
        datasheet_url = (
            f"{_APC_DOWNLOAD_BASE}?p_Doc_Ref={model_upper}_DATASHEET"
            f"&p_enDocType=Product+Data+Sheet"
            f"&p_File_Name={model_upper}_DATASHEET_WW_en-GB.pdf"
        )
        try:
            r = requests.head(
                datasheet_url,
                headers={"User-Agent": _USER_AGENT},
                timeout=10,
            )
            if r.ok and "pdf" in r.headers.get("content-type", "").lower():
                pdf_urls.append(datasheet_url)
        except Exception:
            pass

        # Step 2: Try to scrape the se.com product page for document refs.
        # The page is often blocked by Akamai, so this is best-effort.
        try:
            resp = requests.get(
                f"https://www.se.com/us/en/product/{model_upper}/",
                headers={"User-Agent": _USER_AGENT},
                timeout=10,
                allow_redirects=True,
            )
            if resp.ok:
                # Look for download.schneider-electric.com PDF links
                cdn_urls = re.findall(
                    r'https?://download\.schneider-electric\.com/files\?[^"\'<>\s]+',
                    resp.text,
                )
                for url in cdn_urls:
                    if url not in pdf_urls:
                        # HEAD-check to see if it's a PDF
                        try:
                            hr = requests.head(
                                url,
                                headers={"User-Agent": _USER_AGENT},
                                timeout=10,
                            )
                            if hr.ok and "pdf" in hr.headers.get("content-type", "").lower():
                                pdf_urls.append(url)
                        except Exception:
                            continue

                # Look for SPD_ document references and construct download URLs
                spd_refs = re.findall(r'(SPD_[A-Za-z0-9_-]+)', resp.text)
                seen_refs: set[str] = set()
                for ref in spd_refs:
                    if ref in seen_refs:
                        continue
                    seen_refs.add(ref)
                    # Skip image/thumbnail refs
                    if "_Benefit" in ref or "CENZ-" in ref:
                        continue
                    doc_url = f"{_APC_DOWNLOAD_BASE}?p_Doc_Ref={ref}&p_enDocType=User+guide"
                    if doc_url in pdf_urls:
                        continue
                    try:
                        hr = requests.head(
                            doc_url,
                            headers={"User-Agent": _USER_AGENT},
                            timeout=10,
                        )
                        if hr.ok and "pdf" in hr.headers.get("content-type", "").lower():
                            pdf_urls.append(doc_url)
                    except Exception:
                        continue
        except Exception:
            pass

        return pdf_urls[:5]

    def _search_anker(self, model: str) -> list[str]:
        """Scrape Anker service portal for PDF manual links.

        Anker hosts manuals at service.anker.com/article-description/{slug}
        where slugs start with the model number (e.g. A2331-Anker-323-...).
        PDFs are hosted on an S3 bucket at salesforce-knowledge-download.s3.*.

        Strategy:
        1. Fetch the manuals listing page and look for article links matching
           the model number.
        2. Fetch each matching article page and extract the S3 PDF URL.
        """
        try:
            # Step 1: Fetch manuals listing page and find article links
            resp = requests.get(
                _ANKER_MANUALS_URL,
                headers={"User-Agent": _USER_AGENT},
                timeout=15,
            )
            if not resp.ok:
                return []

            # Find article-description links that contain the model number
            model_upper = model.upper()
            article_pattern = re.compile(
                r'href=["\'](?:https://service\.anker\.com)?'
                r'(/article-description/[^"\']+)["\']',
                re.IGNORECASE,
            )
            article_slugs = []
            for match in article_pattern.finditer(resp.text):
                path = match.group(1)
                # Check if the model number appears in the slug
                if model_upper in path.upper():
                    article_slugs.append(path)

            if not article_slugs:
                return []

            # Step 2: Fetch each article page and extract S3 PDF URLs
            pdf_urls = []
            for slug in article_slugs[:3]:
                try:
                    article_url = f"https://service.anker.com{slug}"
                    r = requests.get(
                        article_url,
                        headers={"User-Agent": _USER_AGENT},
                        timeout=15,
                    )
                    if not r.ok:
                        continue
                    for pdf_match in _ANKER_S3_PDF_RE.finditer(r.text):
                        pdf_url = pdf_match.group(0)
                        if pdf_url not in pdf_urls:
                            pdf_urls.append(pdf_url)
                except Exception:
                    continue
            return pdf_urls
        except Exception:
            return []

    def _search_generic_support(self, model: str, manufacturer: str) -> list[str]:
        """Best-effort search of common manufacturer support URL patterns.

        For manufacturers without a dedicated scraper, try common URL
        patterns where companies host support/download pages. Scrape
        any pages that return 200 for PDF links (href ending in .pdf).
        Returns empty list on any failure -- this is purely heuristic.
        """
        domain = self._guess_domain(manufacturer)
        if not domain:
            return []

        # Common URL patterns for manufacturer support pages
        url_patterns = [
            f"https://{domain}/support/download/{model}/",
            f"https://{domain}/support/{model}/",
            f"https://{domain}/products/{model}/support",
            f"https://support.{domain}/{model}/",
        ]

        pdf_urls: list[str] = []
        for url in url_patterns:
            try:
                resp = requests.get(
                    url,
                    headers={"User-Agent": _USER_AGENT},
                    timeout=10,
                    allow_redirects=True,
                )
                if not resp.ok:
                    continue
                # Scrape for PDF links in href attributes
                hrefs = re.findall(
                    r'href=["\']([^"\']*\.pdf(?:\?[^"\']*)?)["\']',
                    resp.text,
                    re.IGNORECASE,
                )
                for href in hrefs:
                    # Make relative URLs absolute
                    if href.startswith("//"):
                        href = "https:" + href
                    elif href.startswith("/"):
                        href = f"https://{domain}{href}"
                    elif not href.startswith("http"):
                        href = f"https://{domain}/{href}"
                    if href not in pdf_urls:
                        pdf_urls.append(href)
            except Exception:
                continue

        return pdf_urls[:5]

    # --- Tier 1: Internet Archive ---

    def _search_archive_org(self, model: str, manufacturer: str | None = None) -> list[str]:
        """Search Internet Archive's manuals collection."""
        try:
            query = f'collection:manuals "{model}"'
            if manufacturer:
                query += f' "{manufacturer}"'
            resp = requests.get(
                "https://archive.org/advancedsearch.php",
                params={
                    "q": query,
                    "fl[]": ["identifier", "title"],
                    "rows": 5,
                    "output": "json",
                },
                headers={"User-Agent": _USER_AGENT},
                timeout=15,
            )
            if not resp.ok:
                return []
            docs = resp.json().get("response", {}).get("docs", [])
            pdf_urls = []
            for doc in docs[:3]:
                identifier = doc.get("identifier")
                if not identifier:
                    continue
                urls = self._get_archive_pdfs(identifier)
                pdf_urls.extend(urls)
            return pdf_urls
        except Exception:
            return []

    def _get_archive_pdfs(self, identifier: str) -> list[str]:
        """Get PDF URLs from an Internet Archive item."""
        try:
            resp = requests.get(
                f"https://archive.org/metadata/{identifier}/files",
                headers={"User-Agent": _USER_AGENT},
                timeout=10,
            )
            if not resp.ok:
                return []
            files = resp.json().get("result", [])
            return [
                f"https://archive.org/download/{identifier}/{f['name']}"
                for f in files
                if f.get("name", "").lower().endswith(".pdf")
            ][:2]  # Max 2 PDFs per archive item
        except Exception:
            return []

    # --- Tier 2: DuckDuckGo ---

    def _search_ddg(self, query: str) -> list[str]:
        try:
            resp = requests.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
                headers={"User-Agent": _USER_AGENT},
                timeout=15,
            )
            if not resp.ok:
                return []
            # DDG lite wraps results in //duckduckgo.com/l/?uddg=ENCODED_URL
            uddg_urls = re.findall(r'uddg=(https?[^&"]+)', resp.text)
            decoded = [unquote(u) for u in uddg_urls]
            results = []
            for url in decoded:
                lower = url.lower()
                if ".pdf" in lower:
                    results.append(url)
                elif "manualslib.com" in lower and "/manual/" in lower:
                    results.append(url)
                elif "support/download" in lower:
                    results.append(url)
            return results
        except Exception:
            return []

    # --- Shared helpers ---

    def _guess_domain(self, manufacturer: str) -> str | None:
        name = manufacturer.lower().strip()
        name = re.sub(r"[^a-z0-9]", "", name)
        if name:
            return f"{name}.com"
        return None

    def _download_pdf(self, url: str, model: str) -> ManualInfo | None:
        try:
            resp = requests.get(
                url,
                timeout=DOWNLOAD_TIMEOUT,
                stream=True,
                headers={"User-Agent": _USER_AGENT},
            )
            if not resp.ok:
                return None

            content_type = resp.headers.get("content-type", "")
            if "pdf" not in content_type and not url.lower().endswith(".pdf"):
                return None

            content_length = resp.headers.get("content-length")
            if content_length and int(content_length) > MAX_FILE_SIZE:
                return None

            content = resp.content
            size = len(content)

            if not self._check_size(size):
                return None
            if not self._check_aggregate(size):
                return None
            if not is_valid_pdf(content):
                return None
            if self._is_duplicate(content):
                return None

            self._total_size += size

            filename = re.sub(r"[^a-zA-Z0-9_.-]", "_", model)
            path = Path(tempfile.gettempdir()) / f"homebox_manual_{filename}_{len(self._seen_hashes)}.pdf"
            path.write_bytes(content)

            name = Path(url.split("?")[0].split("#")[0]).stem or f"{model} Manual"

            return ManualInfo(path=str(path), name=name)
        except Exception:
            return None
