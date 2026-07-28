from __future__ import annotations

import json
import re
import time
from dataclasses import replace
from datetime import date, datetime
from html.parser import HTMLParser
from typing import Any
from urllib.request import Request, urlopen

from .models import ArticleDetail, ArticleSummary


CLS_BASE_URL = "https://www.cls.cn"
BEIJING_TZ_NAME = "Asia/Shanghai"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
)


class _NextDataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self._capture = False
        self._chunks: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag == "script" and dict(attrs).get("id") == "__NEXT_DATA__":
            self._capture = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._capture:
            self._capture = False

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._chunks.append(data)

    @property
    def data(self) -> str:
        return "".join(self._chunks)


def parse_next_data(html: str) -> dict[str, Any]:
    parser = _NextDataParser()
    parser.feed(html)
    if not parser.data:
        raise ValueError("财联社页面缺少 __NEXT_DATA__")
    data = json.loads(parser.data)
    page_props = data.get("props", {}).get("pageProps")
    if not isinstance(page_props, dict):
        raise ValueError("财联社 __NEXT_DATA__ 缺少 pageProps")
    return page_props


def _normalize_url(value: object) -> str | None:
    if not value:
        return None
    url = str(value).strip()
    if url.startswith("//"):
        url = "https:" + url
    if not url.startswith("https://"):
        return None
    return url


def _article_summary(raw: dict[str, Any], subject_id: int, subject_name: str) -> ArticleSummary:
    article_id = str(raw.get("article_id") or raw.get("id") or "").strip()
    timestamp = int(raw.get("article_time") or raw.get("ctime") or 0)
    if not article_id or not timestamp:
        raise ValueError("财联社文章缺少 article_id 或发布时间")
    from zoneinfo import ZoneInfo

    return ArticleSummary(
        article_id=article_id,
        subject_id=subject_id,
        subject_name=subject_name,
        title=str(raw.get("article_title") or raw.get("title") or "").strip(),
        brief=str(raw.get("article_brief") or raw.get("brief") or "").strip(),
        author=str(raw.get("article_author") or raw.get("author") or "财联社").strip(),
        published_at=datetime.fromtimestamp(timestamp, ZoneInfo(BEIJING_TZ_NAME)),
        cover_image=_normalize_url(raw.get("article_img")),
        url=f"{CLS_BASE_URL}/detail/{article_id}",
    )


class ClsClient:
    def __init__(self, timeout: float = 20.0) -> None:
        self.timeout = timeout

    def _get(self, url: str) -> str:
        last_error: Exception | None = None
        for attempt in range(3):
            request = Request(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml",
                    "Referer": CLS_BASE_URL + "/",
                },
            )
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    return response.read().decode("utf-8")
            except Exception as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(1 << attempt)
        raise RuntimeError(f"财联社请求失败（已重试 3 次）: {url}") from last_error

    def fetch_subject(self, subject_id: int) -> list[ArticleSummary]:
        page_props = parse_next_data(self._get(f"{CLS_BASE_URL}/subject/{subject_id}"))
        data = page_props.get("data")
        if not isinstance(data, dict):
            raise ValueError(f"财联社栏目 {subject_id} 缺少 data")
        subject_name = str(data.get("name") or subject_id)
        articles = data.get("articles")
        if not isinstance(articles, list):
            raise ValueError(f"财联社栏目 {subject_id} 缺少 articles")
        result = [
            _article_summary(raw, subject_id, subject_name)
            for raw in articles
            if isinstance(raw, dict)
        ]
        return sorted(result, key=lambda item: item.published_at, reverse=True)

    def find_article_for_date(
        self, subject_id: int, target_date: date
    ) -> ArticleSummary | None:
        return next(
            (
                article
                for article in self.fetch_subject(subject_id)
                if article.published_at.date() == target_date
            ),
            None,
        )

    def fetch_detail(self, summary: ArticleSummary) -> ArticleDetail:
        page_props = parse_next_data(self._get(summary.url))
        raw = page_props.get("articleDetail")
        if not isinstance(raw, dict):
            raise ValueError(f"财联社文章 {summary.article_id} 缺少 articleDetail")

        audio_url = _normalize_url(raw.get("audioUrl")) or _normalize_url(
            raw.get("miniMaxAudioUrl")
        )
        updated = replace(
            summary,
            title=str(raw.get("title") or summary.title).strip(),
            brief=str(raw.get("brief") or summary.brief).strip(),
            author=str(raw.get("author") or summary.author).strip(),
        )
        return ArticleDetail(
            **updated.__dict__,
            audio_url=audio_url,
            content_html=str(raw.get("content") or ""),
            images=(),
        )


def strip_html(value: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", value, flags=re.IGNORECASE)
    text = re.sub(r"</p\s*>", "\n", text, flags=re.IGNORECASE)
    return re.sub(r"<[^>]+>", "", text).strip()
