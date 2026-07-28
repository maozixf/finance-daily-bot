from __future__ import annotations

import hashlib
import html
import re
from collections import defaultdict
from datetime import date
from html.parser import HTMLParser
from typing import Any

from .models import ArticleDetail, Message


def _digest(*parts: str) -> str:
    return hashlib.sha256("\x00".join(parts).encode("utf-8")).hexdigest()


def _clean_layout(value: str) -> str:
    value = value.replace("\r", "")
    value = re.sub(r"[ \t]+\n", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


class _ArticleLayoutParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.markdown_parts: list[str] = []
        self.text_parts: list[str] = []
        self.links: list[str | None] = []
        self.list_types: list[str] = []
        self.list_counters: list[int] = []

    def _break(self, value: str = "\n\n") -> None:
        self.markdown_parts.append(value)
        self.text_parts.append(value)

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        attributes = dict(attrs)
        if tag == "p":
            self._break()
        elif tag == "br":
            self._break("\n")
        elif tag in {"strong", "b"}:
            self.markdown_parts.append("**")
        elif tag in {"em", "i"}:
            self.markdown_parts.append("*")
        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            level = min(int(tag[1]) + 1, 6)
            self._break("\n\n")
            self.markdown_parts.append("#" * level + " ")
        elif tag in {"ul", "ol"}:
            self.list_types.append(tag)
            self.list_counters.append(0)
            self._break("\n")
        elif tag == "li":
            self._break("\n")
            if self.list_types and self.list_types[-1] == "ol":
                self.list_counters[-1] += 1
                marker = f"{self.list_counters[-1]}. "
            else:
                marker = "- "
            self.markdown_parts.append(marker)
            self.text_parts.append(marker)
        elif tag == "blockquote":
            self._break()
            self.markdown_parts.append("> ")
        elif tag == "a":
            href = str(attributes.get("href") or "")
            href = href if href.startswith("https://") else None
            self.links.append(href)
            if href:
                self.markdown_parts.append("[")
        elif tag in {"tr", "table"}:
            self._break("\n")
        elif tag in {"td", "th"}:
            self.markdown_parts.append(" | ")
            self.text_parts.append(" | ")
        elif tag == "img":
            src = str(attributes.get("src") or "")
            if src.startswith("//"):
                src = "https:" + src
            if src.startswith("https://"):
                alt = str(attributes.get("alt") or "正文图片").strip() or "正文图片"
                self.markdown_parts.append(f"\n\n![{alt}]({src})\n\n")
                self.text_parts.append(f"\n\n正文图片：{src}\n\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"strong", "b"}:
            self.markdown_parts.append("**")
        elif tag in {"em", "i"}:
            self.markdown_parts.append("*")
        elif tag in {"ul", "ol"}:
            if self.list_types:
                self.list_types.pop()
                self.list_counters.pop()
            self._break("\n")
        elif tag == "a":
            href = self.links.pop() if self.links else None
            if href:
                self.markdown_parts.append(f"]({href})")

    def handle_data(self, data: str) -> None:
        self.markdown_parts.append(data)
        self.text_parts.append(data)

    @property
    def markdown(self) -> str:
        return _clean_layout("".join(self.markdown_parts))

    @property
    def text(self) -> str:
        return _clean_layout("".join(self.text_parts))


class _SafeArticleHtmlParser(HTMLParser):
    ALLOWED = {
        "p",
        "br",
        "strong",
        "b",
        "em",
        "i",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "ul",
        "ol",
        "li",
        "blockquote",
        "table",
        "thead",
        "tbody",
        "tr",
        "th",
        "td",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.links: list[bool] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag in self.ALLOWED:
            self.parts.append(f"<{tag}>")
        elif tag == "img":
            attributes = dict(attrs)
            src = str(attributes.get("src") or "")
            if src.startswith("//"):
                src = "https:" + src
            if src.startswith("https://"):
                alt = str(attributes.get("alt") or "正文图片").strip() or "正文图片"
                self.parts.append(
                    f'<img src="{html.escape(src, quote=True)}" '
                    f'alt="{html.escape(alt, quote=True)}" />'
                )
        elif tag == "a":
            href = str(dict(attrs).get("href") or "")
            allowed = href.startswith("https://")
            self.links.append(allowed)
            if allowed:
                self.parts.append(f'<a href="{html.escape(href, quote=True)}">')

    def handle_endtag(self, tag: str) -> None:
        if tag in self.ALLOWED:
            self.parts.append(f"</{tag}>")
        elif tag == "a":
            allowed = self.links.pop() if self.links else False
            if allowed:
                self.parts.append("</a>")

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag == "br":
            self.parts.append("<br />")
        elif tag == "img":
            self.handle_starttag(tag, attrs)

    def handle_data(self, data: str) -> None:
        self.parts.append(html.escape(data))

    @property
    def value(self) -> str:
        return "".join(self.parts)


def _render_original(content_html: str) -> tuple[str, str, str]:
    layout = _ArticleLayoutParser()
    layout.feed(content_html)
    safe_html = _SafeArticleHtmlParser()
    safe_html.feed(content_html)
    return layout.text, layout.markdown, safe_html.value


def render_article(
    feed: str,
    target_date: date,
    article: ArticleDetail,
    *,
    today_hot: list[dict[str, Any]] | None = None,
) -> Message:
    date_text = target_date.isoformat()
    headline = f"{date_text} · {article.title}"
    original_text, original_markdown, original_html = _render_original(
        article.content_html
    )

    sections = [headline]
    if article.brief.strip():
        sections.append("摘要\n" + article.brief.strip())
    if article.audio_url:
        sections.append(f"音频链接：{article.audio_url}")
    if original_text:
        sections.append(original_text)
    sections.append(f"原文链接：{article.url}")
    if today_hot:
        sections.append(
            f"{date_text} · 今日热点\n"
            + "\n\n".join(
                f"{index}. {item.get('title', '')}"
                f"（热度值：{item.get('heat_raw', '')}）\n"
                f"   关键词：{item.get('keyword', '')}"
                for index, item in enumerate(today_hot, start=1)
            )
        )
    text = "\n\n".join(sections)

    markdown_sections = [f"# {headline}"]
    if article.brief.strip():
        quoted_brief = "\n> ".join(article.brief.strip().splitlines())
        markdown_sections.append(f"### 摘要\n\n> {quoted_brief}")
    if article.audio_url:
        markdown_sections.append(f"音频链接：[点击播放]({article.audio_url})")
    if original_markdown:
        markdown_sections.append(original_markdown)
    markdown = "\n\n".join(markdown_sections)
    markdown += "\n\n---\n\n" + f"原文链接：[财联社原文]({article.url})"
    if today_hot:
        markdown += "\n\n---\n\n" + (
            f"## {date_text} · 今日热点\n\n"
            + "\n\n".join(
                f"### {index}. {item.get('title', '')}"
                f"（热度值：{item.get('heat_raw', '')}）\n\n"
                f"关键词：**{item.get('keyword', '')}**"
                for index, item in enumerate(today_hot, start=1)
            )
        )

    html_parts = [
        f"<h1>{html.escape(headline)}</h1>",
    ]
    if article.brief.strip():
        html_parts.append(
            "<h3>摘要</h3><blockquote>"
            + html.escape(article.brief).replace("\n", "<br />")
            + "</blockquote>"
        )
    if article.audio_url:
        html_parts.append(
            f'<p>音频链接：<a href="{html.escape(article.audio_url, quote=True)}">点击播放</a></p>'
        )
    if original_html:
        html_parts.append(original_html)
    html_parts.append("<hr />")
    html_parts.append(
        f'<p>原文链接：<a href="{html.escape(article.url, quote=True)}">财联社原文</a></p>'
    )
    if today_hot:
        html_parts.append(f"<hr /><h2>{html.escape(date_text)} · 今日热点</h2>")
        html_parts.extend(
            f"<h3>{index}. "
            + html.escape(str(item.get("title", "")))
            + "（热度值："
            + html.escape(str(item.get("heat_raw", "")))
            + "）</h3><p>关键词：<strong>"
            + html.escape(str(item.get("keyword", "")))
            + "</strong></p>"
            for index, item in enumerate(today_hot, start=1)
        )
    html_body = "".join(html_parts)
    key = f"{feed}:{target_date.isoformat()}"
    return Message(
        key=key,
        feed=feed,
        date_key=target_date.isoformat(),
        source_id=article.article_id,
        source_url=article.url,
        title=headline,
        text=text,
        markdown=markdown,
        html=html_body,
        images=(),
        metadata={"digest": _digest(text, markdown, html_body)},
    )


def render_calendar(
    start: date, end: date, items: list[dict[str, Any]]
) -> Message:
    grouped: dict[str, list[str]] = defaultdict(list)
    for item in items:
        grouped[str(item.get("date"))].append(str(item.get("event") or "").strip())
    title = f"本周及下周财经日历 · {start:%m-%d} 至 {end:%m-%d}"
    text_sections: list[str] = []
    markdown_sections: list[str] = []
    html_sections: list[str] = []
    for day in grouped:
        events = [event for event in grouped[day] if event]
        text_sections.append(day + "\n" + "\n".join(f"- {event}" for event in events))
        markdown_sections.append(
            f"## {day}\n\n" + "\n".join(f"- {event}" for event in events)
        )
        html_sections.append(
            f"<h2>{html.escape(day)}</h2><ul>"
            + "".join(f"<li>{html.escape(event)}</li>" for event in events)
            + "</ul>"
        )
    text = title + "\n\n" + "\n\n".join(text_sections)
    markdown = f"# {title}\n\n" + "\n\n".join(markdown_sections)
    html_body = f"<h1>{html.escape(title)}</h1>" + "".join(html_sections)
    return Message(
        key=f"weekly:{start.isoformat()}",
        feed="weekly",
        date_key=start.isoformat(),
        source_id=f"{start.isoformat()}_{end.isoformat()}",
        source_url="https://duanxianxia.com/web/hotnews/iframe",
        title=title,
        text=text,
        markdown=markdown,
        html=html_body,
        metadata={
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "digest": _digest(text, markdown, html_body),
        },
    )
