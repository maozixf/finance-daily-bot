from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import date, datetime
from html.parser import HTMLParser
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from .models import ArticleDetail, ArticleSummary


JYS_BASE_URL = "https://www.jiuyangongshe.com"
BEIJING_TZ = ZoneInfo("Asia/Shanghai")
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
)


@dataclass
class _ProfileItem:
    article_id: str = ""
    title: str = ""
    brief: str = ""
    published_at: str = ""


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


class _ProfileParser(HTMLParser):
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
        self.depth = 0
        self.community_depth: int | None = None
        self.item_depth: int | None = None
        self.item: _ProfileItem | None = None
        self.capture_field: str | None = None
        self.capture_depth: int | None = None
        self.capture_parts: list[str] = []
        self.items: list[_ProfileItem] = []

    def _start_capture(self, field: str) -> None:
        if self.item is None:
            return
        self.capture_field = field
        self.capture_depth = self.depth
        self.capture_parts = []

    def _finish_capture(self) -> None:
        if self.item is not None and self.capture_field:
            value = _clean_text("".join(self.capture_parts))
            if value:
                setattr(self.item, self.capture_field, value)
        self.capture_field = None
        self.capture_depth = None
        self.capture_parts = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag not in self.VOID_TAGS:
            self.depth += 1
        attributes = dict(attrs)
        classes = set(str(attributes.get("class") or "").split())

        if tag == "div" and "community-bar" in classes:
            self.community_depth = self.depth
            return
        if self.community_depth is None:
            return
        if tag == "li" and self.item is None:
            self.item = _ProfileItem()
            self.item_depth = self.depth
            return
        if self.item is None:
            return

        if tag == "div" and "fs13-ash" in classes and not self.item.published_at:
            self._start_capture("published_at")
        elif tag == "div" and "book-title" in classes:
            self._start_capture("title")
        elif tag == "a":
            href = str(attributes.get("href") or "")
            match = re.fullmatch(r"/a/([A-Za-z0-9]+)", href)
            if match:
                self.item.article_id = match.group(1)
                self._start_capture("brief")

    def handle_endtag(self, tag: str) -> None:
        if self.capture_depth == self.depth:
            self._finish_capture()
        if tag == "li" and self.item is not None and self.item_depth == self.depth:
            if (
                self.item.article_id
                and self.item.title
                and self.item.published_at
            ):
                self.items.append(self.item)
            self.item = None
            self.item_depth = None
        if (
            tag == "div"
            and self.community_depth is not None
            and self.community_depth == self.depth
        ):
            self.community_depth = None
        self.depth -= 1

    def handle_data(self, data: str) -> None:
        if self.capture_field:
            self.capture_parts.append(data)


class _ImageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.images: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag != "img":
            return
        src = str(dict(attrs).get("src") or "").strip()
        if src.startswith("//"):
            src = "https:" + src
        if src.startswith("https://") and src not in self.images:
            self.images.append(src)


def parse_profile_articles(
    html: str,
    *,
    user_id: str,
    author: str,
    subject_name: str,
) -> list[ArticleSummary]:
    parser = _ProfileParser()
    parser.feed(html)
    articles: list[ArticleSummary] = []
    for item in parser.items:
        try:
            published_at = datetime.strptime(
                item.published_at[:19], "%Y-%m-%d %H:%M:%S"
            ).replace(tzinfo=BEIJING_TZ)
        except ValueError:
            continue
        articles.append(
            ArticleSummary(
                article_id=item.article_id,
                subject_id=0,
                subject_name=subject_name,
                title=item.title,
                brief=item.brief,
                author=author,
                published_at=published_at,
                cover_image=None,
                url=f"{JYS_BASE_URL}/a/{item.article_id}",
                source_label="韭研公社原文",
            )
        )
    return sorted(articles, key=lambda article: article.published_at, reverse=True)


def parse_nuxt_article_content(html: str) -> str:
    marker = "window.__NUXT__="
    start = html.find(marker)
    if start < 0:
        raise ValueError("韭研公社文章页面缺少 window.__NUXT__")
    script = html[start + len(marker) :]
    match = re.search(r"\bcontent:(?=\")", script)
    if not match:
        raise ValueError("韭研公社文章数据缺少 content")
    try:
        content, _ = json.JSONDecoder().raw_decode(script, match.end())
    except json.JSONDecodeError as exc:
        raise ValueError("韭研公社文章 content 解析失败") from exc
    if not isinstance(content, str) or not content.strip():
        raise ValueError("韭研公社文章正文为空")
    return content


class JysClient:
    def __init__(self, timeout: float = 20.0) -> None:
        self.timeout = timeout

    def _get(self, url: str) -> str:
        last_error: Exception | None = None
        separator = "&" if "?" in url else "?"
        cache_busted_url = url + separator + urlencode({"t": int(time.time() * 1000)})
        for attempt in range(3):
            request = Request(
                cache_busted_url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml",
                    "Referer": JYS_BASE_URL + "/",
                    "Cache-Control": "no-cache",
                    "Pragma": "no-cache",
                },
            )
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    return response.read().decode("utf-8")
            except Exception as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(1 << attempt)
        raise RuntimeError(f"韭研公社请求失败（已重试 3 次）: {url}") from last_error

    def fetch_profile(
        self,
        *,
        user_id: str,
        author: str,
        subject_name: str,
    ) -> list[ArticleSummary]:
        html = self._get(f"{JYS_BASE_URL}/u/{user_id}")
        articles = parse_profile_articles(
            html,
            user_id=user_id,
            author=author,
            subject_name=subject_name,
        )
        if not articles:
            raise ValueError(f"韭研公社用户主页未解析到文章: {user_id}")
        return articles

    def find_article_for_date(
        self,
        *,
        user_id: str,
        author: str,
        subject_name: str,
        title_terms: tuple[str, ...],
        target_date: date,
    ) -> ArticleSummary | None:
        return next(
            (
                article
                for article in self.fetch_profile(
                    user_id=user_id,
                    author=author,
                    subject_name=subject_name,
                )
                if article.published_at.date() == target_date
                and all(term in article.title for term in title_terms)
            ),
            None,
        )

    def fetch_detail(self, summary: ArticleSummary) -> ArticleDetail:
        content_html = parse_nuxt_article_content(self._get(summary.url))
        image_parser = _ImageParser()
        image_parser.feed(content_html)
        return ArticleDetail(
            **summary.__dict__,
            audio_url=None,
            content_html=content_html,
            images=tuple(image_parser.images),
        )
