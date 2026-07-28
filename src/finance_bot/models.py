from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class ArticleSummary:
    article_id: str
    subject_id: int
    subject_name: str
    title: str
    brief: str
    author: str
    published_at: datetime
    cover_image: str | None
    url: str


@dataclass(frozen=True)
class ArticleDetail(ArticleSummary):
    audio_url: str | None = None
    content_html: str = ""
    images: tuple[str, ...] = ()


@dataclass(frozen=True)
class Message:
    key: str
    feed: str
    date_key: str
    source_id: str
    source_url: str
    title: str
    text: str
    markdown: str
    html: str
    images: tuple[str, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)
