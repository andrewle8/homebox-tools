"""Clean Amazon SEO-stuffed product titles into readable names."""

import re

# Patterns that indicate SEO junk after them
SEO_CUTOFF_PATTERNS = [
    # Broad "X for" phrases first — they often precede specific "for Device" patterns
    r"\bIdeal for\b",
    r"\bGreat for\b",
    r"\bPerfect for\b",
    r"\bDesigned for\b",
    r"\bBest for\b",
    r"\bfor (?:iPhone|Samsung|Galaxy|iPad|MacBook|Laptop|Home|Office|Kitchen|Bedroom|Bathroom|Car)\b",
    r"\bCompatible [Ww]ith\b",
    r"\bWorks [Ww]ith\b",
    r"\bA Certified\b",
    r"\bCable Not Included\b",
    r"\bLifetime (?:Internet |)Security\b",
    r"\bSeq\. Read\b",
]

TRAILING_COLOR_RE = re.compile(
    r"\s*[-–—]\s*(?:Black|White|Silver|Gray|Grey|Graphite|Blue|Red|Green|Pink|Gold|Space Gray|Midnight|Starlight)\s*$",
    re.IGNORECASE,
)

JUNK_PARENS_RE = re.compile(
    r"\s*\([^)]*(?:Not Included|Renewed|Refurbished|Frustration.Free)[^)]*\)",
    re.IGNORECASE,
)

MODEL_RE = re.compile(r"\(?[A-Z]{1,4}[-]?[A-Z0-9]{2,}[A-Z0-9-]*\)?")

LEADING_BRACKET_TAG_RE = re.compile(r"^(\s*\[[^\]]*\]\s*)+")

DASH_SEPARATOR_RE = re.compile(r"\s*[-–—]\s+")

# Matches a parenthesized group followed by a dash separator, used to cut after model numbers
PAREN_THEN_DASH_RE = re.compile(r"(\([^)]+\))\s*[-–—]\s+")


def _title_case_brand(name: str) -> str:
    words = name.split()
    if not words:
        return name
    result = []
    for word in words:
        has_digit = any(c.isdigit() for c in word)
        if (MODEL_RE.fullmatch(word) and has_digit) or len(word) <= 3 or re.match(r"^\d", word):
            result.append(word)
        elif word.isupper() and len(word) > 3:
            result.append(word.capitalize())
        else:
            result.append(word)
    return " ".join(result)


def clean_name(raw: str) -> str:
    name = raw.strip()
    name = re.sub(r"\s+", " ", name)

    # Strip leading bracket tags like "[Updated 2024]" or "[2 Pack]"
    name = LEADING_BRACKET_TAG_RE.sub("", name).strip()

    name = JUNK_PARENS_RE.sub("", name)

    for pattern in SEO_CUTOFF_PATTERNS:
        match = re.search(pattern, name)
        if match:
            candidate = name[: match.start()].rstrip(" ,;-–—")
            if len(candidate) > 15:
                name = candidate

    name = TRAILING_COLOR_RE.sub("", name)
    name = re.sub(r"\s*[-–—|,;]\s*$", "", name)

    # Cut after parenthesized model number followed by dash separator
    paren_dash = PAREN_THEN_DASH_RE.search(name)
    if paren_dash:
        candidate = name[: paren_dash.end() - len(paren_dash.group(0)) + len(paren_dash.group(1))].strip()
        if len(candidate) > 15:
            name = candidate

    # Truncate at first comma if still too long (Amazon uses commas to separate
    # the product name from feature descriptions)
    if len(name) > 60:
        comma_pos = name.find(",")
        if comma_pos > 15:
            name = name[:comma_pos]

    # Truncate at first dash separator if still too long
    if len(name) > 80:
        match = DASH_SEPARATOR_RE.search(name)
        if match and match.start() > 15:
            name = name[: match.start()]
    name = _title_case_brand(name)
    name = re.sub(r"\s+", " ", name).strip()
    return name
