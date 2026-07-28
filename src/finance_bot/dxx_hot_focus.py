#!/usr/bin/env python3
"""Fetch and normalize the five "热点聚焦" feeds from duanxianxia.com.

The upstream endpoint returns JSON containing server-rendered HTML. This script
converts that HTML into a stable JSON shape suitable for agents and pipelines.
It uses only the Python standard library.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API_URL = "https://duanxianxia.com/api/getHotNewsByType"
REFERER = "https://duanxianxia.com/web/hotnews/iframe"


@dataclass
class SectionSpec:
    key: str
    label: str
    api_type: str
    parser: str


SECTIONS = (
    SectionSpec("hot_news", "热点资讯", "ths", "news"),
    SectionSpec("today_hot", "今日热点", "chaosha", "today"),
    SectionSpec("community_hot", "公社热帖", "jiuyan", "news"),
    SectionSpec("ths_hot", "同花热榜", "hot_stock_hour", "stocks"),
    SectionSpec("finance_calendar", "财经日历", "timeline", "calendar"),
)

ALIASES = {
    "热点资讯": "hot_news",
    "今日热点": "today_hot",
    "公社热帖": "community_hot",
    "同花热榜": "ths_hot",
    "财经日历": "finance_calendar",
    "ths": "hot_news",
    "chaosha": "today_hot",
    "jiuyan": "community_hot",
    "hot_stock_hour": "ths_hot",
    "timeline": "finance_calendar",
}
ALIASES.update({spec.key: spec.key for spec in SECTIONS})


@dataclass
class Node:
    tag: str
    attrs: dict[str, str | None] = field(default_factory=dict)
    children: list[Node | str] = field(default_factory=list)
    parent: Node | None = None

    def text(self) -> str:
        return "".join(
            child if isinstance(child, str) else child.text() for child in self.children
        )

    def classes(self) -> set[str]:
        return set((self.attrs.get("class") or "").split())

    def descendants(self, include_self: bool = False) -> Iterable[Node]:
        if include_self:
            yield self
        for child in self.children:
            if isinstance(child, Node):
                yield child
                yield from child.descendants()

    def find_all(self, predicate: Callable[[Node], bool]) -> list[Node]:
        return [node for node in self.descendants() if predicate(node)]

    def first(self, predicate: Callable[[Node], bool]) -> Node | None:
        return next((node for node in self.descendants() if predicate(node)), None)


class TreeParser(HTMLParser):
    VOID_TAGS = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("root")
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = Node(tag.lower(), dict(attrs), parent=self.stack[-1])
        self.stack[-1].children.append(node)
        if tag.lower() not in self.VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        self.handle_starttag(tag, attrs)
        if self.stack[-1].tag == tag.lower():
            self.stack.pop()

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(data)


def parse_html(html: str) -> Node:
    parser = TreeParser()
    parser.feed(html)
    parser.close()
    return parser.root


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def by_class(class_name: str) -> Callable[[Node], bool]:
    return lambda node: class_name in node.classes()


def first_text(node: Node, class_name: str) -> str | None:
    match = node.first(by_class(class_name))
    return clean_text(match.text()) if match else None


def heat_value(raw: str | None) -> int | float | None:
    if not raw:
        return None
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(万|w)?", raw, re.I)
    if not match:
        return None
    value = float(match.group(1))
    if match.group(2):
        value *= 10_000
    return int(value) if value.is_integer() else value


def parse_news(html: str, label: str) -> list[dict[str, object]]:
    root = parse_html(html)
    items = root.find_all(by_class("item"))
    output: list[dict[str, object]] = []
    for index, item in enumerate(items, 1):
        title_box = item.first(by_class("info-title"))
        link = title_box.first(lambda node: node.tag == "a") if title_box else None
        resource = first_text(item, "overflowtxt") or ""
        heat_match = re.search(r"热度[：:]?\s*([0-9.]+\s*(?:万|w)?)", resource, re.I)
        heat_raw = heat_match.group(1).replace(" ", "") if heat_match else None
        output.append(
            {
                "rank": index,
                "title": clean_text(link.text()) if link else clean_text(item.text()),
                "url": link.attrs.get("href") if link else None,
                "published_at": first_text(item, "time"),
                "heat": heat_value(heat_raw),
                "heat_raw": heat_raw,
                "source": label,
            }
        )
    return output


def element_children(node: Node) -> list[Node]:
    return [child for child in node.children if isinstance(child, Node)]


def parse_today(html: str) -> list[dict[str, object]]:
    root = parse_html(html)
    output: list[dict[str, object]] = []
    for panel in root.find_all(by_class("panel")):
        date = first_text(panel, "panel-heading")
        body = panel.first(by_class("panel-body"))
        if not body:
            continue
        children = element_children(body)
        for index, child in enumerate(children):
            if "keyword" not in child.classes():
                continue
            detail = children[index + 1] if index + 1 < len(children) else None
            keyword_node = detail.first(lambda node: node.tag == "i") if detail else None
            heat_node = detail.first(lambda node: node.tag == "span") if detail else None
            heat_text = clean_text(heat_node.text()) if heat_node else None
            heat_match = (
                re.search(r"热度值[：:]?\s*([0-9.]+\s*(?:万|w)?)", heat_text, re.I)
                if heat_text
                else None
            )
            heat_raw = heat_match.group(1).replace(" ", "") if heat_match else None
            output.append(
                {
                    "rank": len(output) + 1,
                    "date": date,
                    "title": clean_text(child.text()),
                    "keyword": clean_text(keyword_node.text()) if keyword_node else None,
                    "heat": heat_value(heat_raw),
                    "heat_raw": heat_raw,
                }
            )
    return output


def parse_stocks(html: str) -> list[dict[str, object]]:
    root = parse_html(html)
    output: list[dict[str, object]] = []
    for index, item in enumerate(root.find_all(by_class("item")), 1):
        link = item.first(by_class("kline"))
        title_box = item.first(by_class("info-title"))
        title_text = clean_text(title_box.text()) if title_box else ""
        heat_match = re.search(r"([0-9.]+\s*(?:万|w)?)\s*热度", title_text, re.I)
        heat_raw = heat_match.group(1).replace(" ", "") if heat_match else None
        tags = [clean_text(node.text()) for node in item.find_all(by_class("tag"))]
        output.append(
            {
                "rank": index,
                "code": link.attrs.get("code") if link else None,
                "name": clean_text(link.text()) if link else None,
                "heat": heat_value(heat_raw),
                "heat_raw": heat_raw,
                "tags": tags,
            }
        )
    return output


def parse_calendar(html: str) -> list[dict[str, object]]:
    root = parse_html(html)
    output: list[dict[str, object]] = []
    for panel in root.find_all(by_class("panel")):
        date = first_text(panel, "panel-heading")
        for event in panel.find_all(by_class("list-group-item")):
            output.append(
                {
                    "date": date,
                    "event": clean_text(event.text()),
                }
            )
    return output


PARSERS = {
    "news": lambda html, spec: parse_news(html, spec.label),
    "today": lambda html, spec: parse_today(html),
    "stocks": lambda html, spec: parse_stocks(html),
    "calendar": lambda html, spec: parse_calendar(html),
}


def fetch_raw(api_type: str, timeout: float) -> dict[str, object]:
    payload = urlencode({"type": api_type}).encode("ascii")
    request = Request(
        API_URL,
        data=payload,
        method="POST",
        headers={
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": "https://duanxianxia.com",
            "Referer": REFERER,
            "User-Agent": "Mozilla/5.0 (compatible; HotFocusAgent/1.0)",
            "X-Requested-With": "XMLHttpRequest",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return json.loads(response.read().decode(charset))


def fetch_section(
    spec: SectionSpec,
    timeout: float,
    limit: int,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, object]:
    raw = fetch_raw(spec.api_type, timeout)
    if raw.get("result") != "success":
        raise RuntimeError(f"upstream returned result={raw.get('result')!r}")
    html = raw.get("html")
    if not isinstance(html, str):
        raise RuntimeError("upstream response does not contain an HTML string")
    items = PARSERS[spec.parser](html, spec)
    if spec.parser == "calendar" and (date_from or date_to):
        items = [
            item
            for item in items
            if (not date_from or date.fromisoformat(str(item["date"])) >= date_from)
            and (not date_to or date.fromisoformat(str(item["date"])) <= date_to)
        ]
    if limit > 0:
        items = items[:limit]
    result: dict[str, object] = {
        "label": spec.label,
        "api_type": spec.api_type,
        "count": len(items),
        "items": items,
    }
    if raw.get("stock_url"):
        result["quote_url"] = raw["stock_url"]
    if raw.get("cdate"):
        result["current_date"] = raw["cdate"]
    if spec.parser == "calendar" and (date_from or date_to):
        result["date_range"] = {
            "from": date_from.isoformat() if date_from else None,
            "to": date_to.isoformat() if date_to else None,
        }
    return result


def resolve_sections(value: str) -> list[SectionSpec]:
    if value.strip().lower() == "all":
        return list(SECTIONS)
    requested = [part.strip() for part in value.split(",") if part.strip()]
    keys: list[str] = []
    for name in requested:
        key = ALIASES.get(name)
        if not key:
            valid = ", ".join(["all", *[spec.key for spec in SECTIONS], *ALIASES.keys()])
            raise ValueError(f"unknown section {name!r}; valid values: {valid}")
        if key not in keys:
            keys.append(key)
    return [spec for spec in SECTIONS if spec.key in keys]


def build_output(
    specs: list[SectionSpec],
    timeout: float,
    limit: int,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, object]:
    sections: dict[str, object] = {}
    errors: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=len(specs)) as executor:
        futures = {
            executor.submit(
                fetch_section, spec, timeout, limit, date_from, date_to
            ): spec
            for spec in specs
        }
        completed: dict[str, dict[str, object]] = {}
        for future in as_completed(futures):
            spec = futures[future]
            try:
                completed[spec.key] = future.result()
            except Exception as exc:  # Keep partial data useful to an agent.
                errors[spec.key] = f"{type(exc).__name__}: {exc}"
    for spec in specs:
        if spec.key in completed:
            sections[spec.key] = completed[spec.key]
    output: dict[str, object] = {
        "schema_version": "1.0",
        "source": API_URL,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "sections": sections,
    }
    if errors:
        output["errors"] = errors
    return output


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch 短线侠热点聚焦 and emit normalized JSON."
    )
    parser.add_argument(
        "--section",
        default="all",
        help="all, comma-separated English keys, API types, or Chinese labels",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="maximum items per section; use 0 for all (default: 20)",
    )
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument(
        "--week",
        choices=("current",),
        help="for 财经日历, keep the current Beijing-time Monday through Sunday",
    )
    parser.add_argument(
        "--from-date",
        type=date.fromisoformat,
        metavar="YYYY-MM-DD",
        help="for 财经日历, inclusive start date",
    )
    parser.add_argument(
        "--to-date",
        type=date.fromisoformat,
        metavar="YYYY-MM-DD",
        help="for 财经日历, inclusive end date",
    )
    parser.add_argument("--output", type=Path, help="write JSON to this file")
    parser.add_argument("--pretty", action="store_true", help="pretty-print JSON")
    args = parser.parse_args()

    if args.limit < 0:
        parser.error("--limit must be >= 0")
    if args.week and (args.from_date or args.to_date):
        parser.error("--week cannot be combined with --from-date or --to-date")
    date_from = args.from_date
    date_to = args.to_date
    if args.week == "current":
        beijing_now = datetime.now(timezone(timedelta(hours=8))).date()
        date_from = beijing_now - timedelta(days=beijing_now.weekday())
        date_to = date_from + timedelta(days=6)
    if date_from and date_to and date_from > date_to:
        parser.error("--from-date must not be later than --to-date")
    try:
        specs = resolve_sections(args.section)
        output = build_output(specs, args.timeout, args.limit, date_from, date_to)
    except (ValueError, HTTPError, URLError, TimeoutError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    serialized = json.dumps(
        output,
        ensure_ascii=False,
        indent=2 if args.pretty else None,
        separators=None if args.pretty else (",", ":"),
    )
    if args.output:
        args.output.write_text(serialized + "\n", encoding="utf-8")
    else:
        print(serialized)
    return 2 if output.get("errors") else 0


if __name__ == "__main__":
    raise SystemExit(main())
