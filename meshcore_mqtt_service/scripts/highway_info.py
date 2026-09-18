#!/usr/bin/env python3
"""Print current Caltrans highway information for a highway number."""

from __future__ import annotations

import argparse
import re
import sys
import textwrap
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


BASE_URL = "https://roads.dot.ca.gov/"
REPORT_MARKER = "This highway information is the latest reported"
NO_RESTRICTIONS_MESSAGE = "No Traffic Restrictions Reported"
OUTPUT_WIDTH = 120

# Familiar short codes for California locations commonly found in Caltrans reports.
# The explicit codes requested by the user take precedence over airport codes.
PLACE_ABBREVIATIONS = (
    ("San Bernardino", "SBD"),
    ("San Francisco", "SF"),
    ("San Luis Obispo", "SLO"),
    ("Santa Barbara", "SB"),
    ("Santa Monica", "SMO"),
    ("Santa Rosa", "SRO"),
    ("Santa Cruz", "SCZ"),
    ("Los Angeles", "LA"),
    ("Sacramento", "SAC"),
    ("Bakersfield", "BAK"),
    ("Long Beach", "LB"),
    ("Palm Springs", "PSP"),
    ("South Lake Tahoe", "SLT"),
    ("San Diego", "SD"),
    ("San Jose", "SJ"),
    ("Oakland", "OAK"),
    ("Stockton", "STK"),
    ("Riverside", "RIV"),
    ("Fresno", "FRE"),
    ("Monterey", "MON"),
    ("Eureka", "EUR"),
    ("Redding", "RED"),
    ("Chico", "CHI"),
    ("Tahoe", "TAH"),
)

DAY_ABBREVIATIONS = (
    ("Monday", "Mon"),
    ("Tuesday", "Tue"),
    ("Wednesday", "Wed"),
    ("Thursday", "Thu"),
    ("Friday", "Fri"),
    ("Saturday", "Sat"),
    ("Sunday", "Sun"),
)

# Ordered longest-first so a phrase is abbreviated before its individual words.
ABBREVIATIONS = (
    (r"\btraffic restrictions\b", "trfc restr."),
    (r"\btraffic restriction\b", "trfc restr."),
    (r"\bCalifornia Highway Patrol\b", "CHP"),
    (r"\balternate route\b", "alt. rte."),
    (r"\bone-way controlled traffic\b", "1way ctrl. trfc"),
    (r"\b1-way controlled traffic\b", "1way ctrl. trfc"),
    (r"\bnorthbound\b", "NB"),
    (r"\bsouthbound\b", "SB"),
    (r"\beastbound\b", "EB"),
    (r"\bwestbound\b", "WB"),
    (r"\bconstruction\b", "constr."),
    (r"\bapproximately\b", "approx."),
    (r"\bconnector\b", "conn."),
    (r"\bmotorists\b", "drivers"),
    (r"\brecommended\b", "recom."),
    (r"\brequired\b", "req'd"),
    (r"\bvehicles\b", "vehs."),
    (r"\btrailers\b", "trlrs"),
    (r"\bcampers\b", "cmprs"),
    (r"\bhighway\b", "Hwy"),
    (r"\bavenue\b", "Ave."),
    (r"\bboulevard\b", "Blvd."),
    (r"\broad\b", "Rd."),
    (r"\bstreet\b", "St."),
    (r"\bminutes\b", "min"),
    (r"\bhours\b", "hrs"),
    (r"\bmiles\b", "mi"),
    (r"\blanes\b", "lns"),
    (r"\blane\b", "ln"),
    (r"\bclosed\b", "clsd"),
    (r"\bclosure\b", "clsr"),
    (r"\bthrough\b", "thru"),
    (r"\bbetween\b", "btwn"),
    (r"\bbrake\b", "brk"),
    (r"\bcheck\b", "chk"),
    (r"\bwest\b", "W"),
    (r"\beast\b", "E"),
    (r"\bnorth\b", "N"),
    (r"\bsouth\b", "S"),
)


class HighwayReportParser(HTMLParser):
    """Extract the highway report, which runs from its timestamp to the next rule."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.capturing = False
        self.finished = False
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.capturing and tag == "hr":
            self.finished = True
            self.capturing = False
        elif self.capturing and tag in {"br", "p", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if self.capturing and tag in {"p", "h1", "h2", "h3", "h4", "strong"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.finished:
            return
        if not self.capturing and REPORT_MARKER in data:
            self.capturing = True
        if self.capturing:
            self.parts.append(data)

    def text(self) -> str:
        lines = []
        for line in "".join(self.parts).splitlines():
            clean_line = re.sub(r"\s+", " ", line).strip()
            if clean_line:
                lines.append(clean_line)
        return "\n".join(lines)


def is_clear_status(text: str) -> bool:
    """Return True when a subsection explicitly reports no road issues."""
    normalized = re.sub(r"\s+", " ", text).strip(" .").lower()
    return bool(
        re.fullmatch(
            r"no (?:traffic restrictions?|advisories|accidents) "
            r"(?:are |were )?(?:currently )?(?:reported|found)"
            r"(?: for this area| on this highway)?",
            normalized,
        )
    )


def traffic_conditions_only(report: str) -> str:
    """Return active condition text without report, highway, or area headings."""
    lines = report.splitlines()
    first_section = next(
        (index for index, line in enumerate(lines) if line.startswith("[") and line.endswith("]")),
        None,
    )

    # Some highway pages give one status without any bracketed area headings.
    if first_section is None:
        condition_lines = [line for line in lines if REPORT_MARKER not in line]
        if condition_lines:
            # The first remaining line is the highway heading (for example, "I 80").
            condition_lines = condition_lines[1:]
        condition_text = "\n".join(condition_lines)
        return NO_RESTRICTIONS_MESSAGE if is_clear_status(condition_text) else condition_text

    sections: list[list[str]] = []
    current: list[str] = []
    for line in lines[first_section:]:
        if line.startswith("[") and line.endswith("]"):
            if current:
                sections.append(current)
            current = [line]
        else:
            current.append(line)
    if current:
        sections.append(current)

    active_sections = [section for section in sections if not is_clear_status(" ".join(section[1:]))]
    if not active_sections:
        return NO_RESTRICTIONS_MESSAGE

    # A blank line preserves the boundary between highway subsections.
    return "\n\n".join("\n".join(section[1:]) for section in active_sections)


def compact_24_hour_time(match: re.Match[str]) -> str:
    """Convert a Caltrans 24-hour time such as 2300 hrs to 11P."""
    hour_24 = int(match.group(1))
    minutes = match.group(2)
    suffix = "A" if hour_24 < 12 else "P"
    hour_12 = hour_24 % 12 or 12
    return f"{hour_12}{':' + minutes if minutes != '00' else ''}{suffix}"


def compact_ampm_time(match: re.Match[str]) -> str:
    """Convert a time such as 8:00 PM to 8P."""
    hour = int(match.group(1))
    minutes = match.group(2) or "00"
    suffix = match.group(3)[0].upper()
    return f"{hour}{':' + minutes if minutes != '00' else ''}{suffix}"


def compact_and_wrap(text: str) -> str:
    """Abbreviate wording and wrap each subsection as a separate text block."""
    if text == NO_RESTRICTIONS_MESSAGE:
        return text

    output_blocks: list[str] = []
    for block in re.split(r"\n\s*\n", text.strip()):
        compact = re.sub(r"\s+", " ", block).strip()
        compact = re.sub(r"\s*/in ([^/]+)/\s*", r" in \1 ", compact)
        # "in Sacramento (Sacramento Co)" repeats the same place name.
        compact = re.sub(
            r"\bin ([A-Za-z .'-]+) \(\1 Co\)",
            r"in \1 Co",
            compact,
            flags=re.I,
        )
        for place, code in PLACE_ABBREVIATIONS:
            compact = re.sub(rf"\b{re.escape(place)}\b", code, compact, flags=re.I)
        for day, code in DAY_ABBREVIATIONS:
            compact = re.sub(rf"\b{day}\b", code, compact, flags=re.I)
        compact = re.sub(
            r"\b([01]\d|2[0-3])([0-5]\d)\s*hrs\b",
            compact_24_hour_time,
            compact,
            flags=re.I,
        )
        compact = re.sub(
            r"\b(1[0-2]|0?[1-9])(?::([0-5]\d))?\s*([AP])\.?M\.?\b",
            compact_ampm_time,
            compact,
            flags=re.I,
        )
        compact = re.sub(r"\b(\d{1,2}(?::\d{2})?[AP]) each (?:morning|night)\b", r"\1", compact)
        compact = re.sub(r"\bMotorists are advised to use\b", "use", compact, flags=re.I)
        compact = re.sub(r"\bTravel is not recommended for\b", "Not recom. for", compact, flags=re.I)
        for pattern, replacement in ABBREVIATIONS:
            compact = re.sub(pattern, replacement, compact, flags=re.I)
        compact = re.sub(r"\s+([,.])", r"\1", compact)
        compact = re.sub(r"\.{2,}", ".", compact)
        compact = re.sub(r"\s+-\s+", "; ", compact)
        compact = re.sub(r"\s+", " ", compact).strip()

        output_blocks.append(
            "\n".join(
                textwrap.wrap(
                    compact,
                    width=OUTPUT_WIDTH,
                    break_long_words=True,
                    break_on_hyphens=False,
                )
            )
        )

    return "\n\n".join(output_blocks)


def highway_number(value: str) -> int:
    """Validate a command-line or prompted highway number."""
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("highway number must be an integer") from exc
    if not 1 <= number <= 999:
        raise argparse.ArgumentTypeError("highway number must be from 1 to 999")
    return number


def fetch_highway_info(number: int) -> str:
    url = f"{BASE_URL}?{urlencode({'roadnumber': number})}"
    request = Request(url, headers={"User-Agent": "Caltrans-highway-info/1.0"})
    with urlopen(request, timeout=20) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        page = response.read().decode(charset, errors="replace")

    parser = HighwayReportParser()
    parser.feed(page)
    report = parser.text()
    if not report:
        raise RuntimeError("the highway information section was not found on the page")
    return compact_and_wrap(traffic_conditions_only(report))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Print current California highway information from Caltrans."
    )
    parser.add_argument(
        "number",
        nargs="?",
        type=highway_number,
        help="highway number from 1 to 999 (prompted for if omitted)",
    )
    args = parser.parse_args()

    if args.number is None:
        try:
            args.number = highway_number(input("Highway number (1-999): ").strip())
        except (EOFError, argparse.ArgumentTypeError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 2

    try:
        print(fetch_highway_info(args.number))
    except (HTTPError, URLError, TimeoutError, RuntimeError) as exc:
        print(f"Error: unable to retrieve highway information: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
