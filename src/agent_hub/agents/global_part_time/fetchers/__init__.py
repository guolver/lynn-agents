"""Shared utilities for job source fetchers.

Each fetcher module (remoteok, remotive, etc.) imports strip_html and
_SSL_CONTEXT from here instead of duplicating them.
"""

from __future__ import annotations

import re
import ssl
from collections.abc import Callable
from html.parser import HTMLParser

try:
    import certifi

    _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL_CONTEXT = None


class _TagStripper(HTMLParser):
    """Collect text nodes from an HTML fragment."""

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def get_text(self) -> str:
        return " ".join(self._parts)


_SAFE_TAGS = frozenset(
    [
        "p", "br", "strong", "b", "em", "i", "u",
        "h1", "h2", "h3", "h4", "h5", "h6",
        "ul", "ol", "li",
        "a", "span", "div",
        "table", "thead", "tbody", "tr", "th", "td",
        "blockquote", "pre", "code", "hr",
    ]
)

_SAFE_ATTRS = frozenset(["href", "target", "rel"])


class _HtmlSanitizer(HTMLParser):
    """Keep only safe structural HTML tags, strip scripts/styles/events."""

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip = 0  # depth inside unsafe tags like <script>/<style>

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style", "iframe", "object", "embed", "form"):
            self._skip += 1
            return
        if self._skip:
            return
        if tag in _SAFE_TAGS:
            safe_attrs = ""
            if tag == "a":
                filtered = [(k, v) for k, v in attrs if k in _SAFE_ATTRS and v]
                if filtered:
                    safe_attrs = " " + " ".join(f'{k}="{v}"' for k, v in filtered)
                safe_attrs += ' rel="noopener noreferrer" target="_blank"'
            self._parts.append(f"<{tag}{safe_attrs}>")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "iframe", "object", "embed", "form"):
            self._skip = max(0, self._skip - 1)
            return
        if self._skip:
            return
        if tag in _SAFE_TAGS:
            self._parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        self._parts.append(data)

    def get_html(self) -> str:
        return "".join(self._parts).strip()


# Country name / city → ISO 3166-1 alpha-2 lookup.
# Covers common values seen from RemoteOK and Remotive location fields.
_COUNTRY_ALIASES: dict[str, str] = {
    "united states": "US",
    "usa": "US",
    "us": "US",
    "u.s.": "US",
    "u.s.a.": "US",
    "united kingdom": "GB",
    "uk": "GB",
    "england": "GB",
    "scotland": "GB",
    "canada": "CA",
    "australia": "AU",
    "germany": "DE",
    "deutschland": "DE",
    "france": "FR",
    "brazil": "BR",
    "brasil": "BR",
    "india": "IN",
    "japan": "JP",
    "china": "CN",
    "south korea": "KR",
    "korea": "KR",
    "mexico": "MX",
    "méxico": "MX",
    "spain": "ES",
    "españa": "ES",
    "italy": "IT",
    "italia": "IT",
    "netherlands": "NL",
    "holland": "NL",
    "sweden": "SE",
    "norway": "NO",
    "denmark": "DK",
    "finland": "FI",
    "switzerland": "CH",
    "austria": "AT",
    "belgium": "BE",
    "portugal": "PT",
    "ireland": "IE",
    "poland": "PL",
    "czech republic": "CZ",
    "czechia": "CZ",
    "romania": "RO",
    "hungary": "HU",
    "greece": "GR",
    "turkey": "TR",
    "türkiye": "TR",
    "russia": "RU",
    "ukraine": "UA",
    "israel": "IL",
    "singapore": "SG",
    "malaysia": "MY",
    "indonesia": "ID",
    "thailand": "TH",
    "vietnam": "VN",
    "philippines": "PH",
    "pakistan": "PK",
    "bangladesh": "BD",
    "sri lanka": "LK",
    "egypt": "EG",
    "south africa": "ZA",
    "nigeria": "NG",
    "kenya": "KE",
    "colombia": "CO",
    "argentina": "AR",
    "chile": "CL",
    "peru": "PE",
    "new zealand": "NZ",
    "taiwan": "TW",
    "hong kong": "HK",
    "united arab emirates": "AE",
    "uae": "AE",
    "saudi arabia": "SA",
    "lebanon": "LB",
    "jordan": "JO",
    "qatar": "QA",
    "costa rica": "CR",
    "uruguay": "UY",
    "ecuador": "EC",
    "croatia": "HR",
    "serbia": "RS",
    "bulgaria": "BG",
    "estonia": "EE",
    "latvia": "LV",
    "lithuania": "LT",
    "slovakia": "SK",
    "slovenia": "SI",
}

# City → country code for common values from job boards
_CITY_TO_COUNTRY: dict[str, str] = {
    "new york": "US",
    "san francisco": "US",
    "los angeles": "US",
    "chicago": "US",
    "seattle": "US",
    "austin": "US",
    "boston": "US",
    "denver": "US",
    "miami": "US",
    "atlanta": "US",
    "dallas": "US",
    "houston": "US",
    "portland": "US",
    "alaska": "US",
    "california": "US",
    "texas": "US",
    "florida": "US",
    "london": "GB",
    "manchester": "GB",
    "edinburgh": "GB",
    "bristol": "GB",
    "berlin": "DE",
    "munich": "DE",
    "hamburg": "DE",
    "frankfurt": "DE",
    "paris": "FR",
    "lyon": "FR",
    "toronto": "CA",
    "vancouver": "CA",
    "montreal": "CA",
    "sydney": "AU",
    "melbourne": "AU",
    "brisbane": "AU",
    "adelaide": "AU",
    "perth": "AU",
    "tokyo": "JP",
    "osaka": "JP",
    "amsterdam": "NL",
    "dublin": "IE",
    "lisbon": "PT",
    "barcelona": "ES",
    "madrid": "ES",
    "milan": "IT",
    "rome": "IT",
    "stockholm": "SE",
    "oslo": "NO",
    "copenhagen": "DK",
    "helsinki": "FI",
    "zurich": "CH",
    "vienna": "AT",
    "brussels": "BE",
    "warsaw": "PL",
    "prague": "CZ",
    "budapest": "HU",
    "bucharest": "RO",
    "são paulo": "BR",
    "sao paulo": "BR",
    "rio de janeiro": "BR",
    "mumbai": "IN",
    "bangalore": "IN",
    "bengaluru": "IN",
    "delhi": "IN",
    "hyderabad": "IN",
    "pune": "IN",
    "chennai": "IN",
    "singapore": "SG",
    "manila": "PH",
    "jakarta": "ID",
    "bangkok": "TH",
    "dubai": "AE",
    "abu dhabi": "AE",
    "tel aviv": "IL",
    "buenos aires": "AR",
    "bogota": "CO",
    "lima": "PE",
    "mexico city": "MX",
    "ciudad de méxico": "MX",
    "cape town": "ZA",
    "johannesburg": "ZA",
    "lagos": "NG",
    "nairobi": "KE",
    "cairo": "EG",
    "istanbul": "TR",
    "seoul": "KR",
    "taipei": "TW",
}

_GLOBAL_KEYWORDS = {"worldwide", "global", "anywhere", "remote", "earth", "everywhere"}
_REGION_KEYWORDS = {
    "europe": [
        "GB",
        "DE",
        "FR",
        "ES",
        "IT",
        "NL",
        "SE",
        "NO",
        "DK",
        "FI",
        "CH",
        "AT",
        "BE",
        "PT",
        "IE",
        "PL",
        "CZ",
        "RO",
        "HU",
        "GR",
        "HR",
        "RS",
        "BG",
        "EE",
        "LV",
        "LT",
        "SK",
        "SI",
    ],
    "latin america": ["BR", "MX", "AR", "CO", "CL", "PE", "EC", "UY", "CR"],
    "latam": ["BR", "MX", "AR", "CO", "CL", "PE", "EC", "UY", "CR"],
    "asia": ["CN", "JP", "KR", "IN", "SG", "MY", "ID", "TH", "VN", "PH", "TW", "HK"],
    "asia pacific": [
        "CN",
        "JP",
        "KR",
        "IN",
        "SG",
        "MY",
        "ID",
        "TH",
        "VN",
        "PH",
        "TW",
        "HK",
        "AU",
        "NZ",
    ],
    "apac": ["CN", "JP", "KR", "IN", "SG", "MY", "ID", "TH", "VN", "PH", "TW", "HK", "AU", "NZ"],
    "north america": ["US", "CA", "MX"],
    "emea": [
        "GB",
        "DE",
        "FR",
        "ES",
        "IT",
        "NL",
        "SE",
        "NO",
        "DK",
        "FI",
        "CH",
        "AT",
        "BE",
        "PT",
        "IE",
        "PL",
        "EG",
        "ZA",
        "NG",
        "KE",
        "AE",
        "SA",
        "IL",
    ],
}


def normalize_countries(raw_locations: list[str]) -> list[str]:
    """Convert free-text location strings to ISO 3166-1 alpha-2 codes.

    Returns ["GLOBAL"] for worldwide/remote-anywhere jobs.
    """
    codes: set[str] = set()
    for loc in raw_locations:
        cleaned = re.sub(r"[,;|/]+$", "", loc.strip()).strip()
        lowered = cleaned.lower()

        if lowered in _GLOBAL_KEYWORDS:
            return ["GLOBAL"]

        # Already an ISO code (2 uppercase letters)?
        if re.fullmatch(r"[A-Z]{2}", cleaned):
            codes.add(cleaned)
            continue

        # Direct country name match
        if lowered in _COUNTRY_ALIASES:
            codes.add(_COUNTRY_ALIASES[lowered])
            continue

        # Region match
        if lowered in _REGION_KEYWORDS:
            codes.update(_REGION_KEYWORDS[lowered])
            continue

        # Try matching each segment of a compound location like
        # "New York, New York, United States"
        parts = [p.strip() for p in re.split(r"[,;|/]", cleaned) if p.strip()]
        matched = False
        for part in parts:
            part_lower = part.lower()
            if part_lower in _COUNTRY_ALIASES:
                codes.add(_COUNTRY_ALIASES[part_lower])
                matched = True
            elif part_lower in _CITY_TO_COUNTRY:
                codes.add(_CITY_TO_COUNTRY[part_lower])
                matched = True
            elif part_lower in _REGION_KEYWORDS:
                codes.update(_REGION_KEYWORDS[part_lower])
                matched = True

        # If nothing matched, try substring matching on the full string
        if not matched:
            for name, code in _COUNTRY_ALIASES.items():
                if name in lowered:
                    codes.add(code)
                    matched = True
                    break
            if not matched:
                for city, code in _CITY_TO_COUNTRY.items():
                    if city in lowered:
                        codes.add(code)
                        matched = True
                        break

        # If still nothing, treat as GLOBAL (benefit of the doubt for remote jobs)
        if not matched:
            codes.add("GLOBAL")

    return sorted(codes) if codes else ["GLOBAL"]


def strip_html(html: str) -> str:
    """Remove HTML tags and return collapsed plain text."""
    stripper = _TagStripper()
    stripper.feed(html)
    text = stripper.get_text()
    return re.sub(r"\s+", " ", text).strip()


def sanitize_html(html: str) -> str:
    """Keep safe structural HTML tags, remove scripts/styles/event handlers."""
    if not html:
        return ""
    sanitizer = _HtmlSanitizer()
    sanitizer.feed(html)
    return sanitizer.get_html()


def get_fetcher(base_url: str) -> tuple[Callable, Callable] | None:
    """Return ``(fetch_fn, map_job_fn)`` for *base_url*, or ``None`` if unrecognised."""
    from .himalayas import fetch as himalayas_fetch, map_job as himalayas_map
    from .jobicy import fetch as jobicy_fetch, map_job as jobicy_map
    from .remoteok import fetch as remoteok_fetch, map_job as remoteok_map
    from .remotive import fetch as remotive_fetch, map_job as remotive_map

    _REGISTRY: dict[str, tuple[Callable, Callable]] = {
        "remoteok.com": (remoteok_fetch, remoteok_map),
        "remotive.com": (remotive_fetch, remotive_map),
        "jobicy.com": (jobicy_fetch, jobicy_map),
        "himalayas.app": (himalayas_fetch, himalayas_map),
    }
    for domain, funcs in _REGISTRY.items():
        if domain in base_url:
            return funcs
    return None
