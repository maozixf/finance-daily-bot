from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .cls_source import ClsClient
from .delivery import load_channel_config, push_message
from .dxx_source import DxxClient
from .jys_source import JysClient
from .models import Message
from .render import render_article, render_calendar, render_today_hot
from .state import DeliveryState


BEIJING_TZ = ZoneInfo("Asia/Shanghai")
SUBJECTS = {
    "morning": 1151,
    "focus": 1135,
    # Retained for manual use only; no scheduled workflow calls this job.
    "close": 1139,
    "weekend": 12471,
}
JYS_JOBS = {
    "pre_market": {
        "user_id": "4df747be1bf143a998171ef03559b517",
        "author": "盘前纪要",
        "subject_name": "盘前纪要",
        "title_terms": ("盘前纪要",),
    },
    "limit_review": {
        "user_id": "276f83dafc624053b4e6a136d3a108f4",
        "author": "股海里扎猛子",
        "subject_name": "连板复盘",
        "title_terms": ("连板", "复盘"),
    },
}
GROUPS = {
    "morning_scan": ("morning", "pre_market"),
    "close_scan": ("focus", "limit_review"),
}


def build_message(job: str, target_date: date) -> Message | None:
    if job == "today_hot":
        items = DxxClient().today_hot(target_date)
        if not items:
            return None
        return render_today_hot(target_date, items)

    if job == "weekly":
        start, end, items = DxxClient().two_week_calendar(target_date)
        if not items:
            return None
        return render_calendar(start, end, items)

    if job in JYS_JOBS:
        spec = JYS_JOBS[job]
        client = JysClient()
        summary = client.find_article_for_date(
            user_id=str(spec["user_id"]),
            author=str(spec["author"]),
            subject_name=str(spec["subject_name"]),
            title_terms=tuple(str(term) for term in spec["title_terms"]),
            target_date=target_date,
        )
        if summary is None:
            return None
        article = client.fetch_detail(summary)
        today_hot = None
        if job == "limit_review":
            today_hot = DxxClient().today_hot(target_date)
            if not today_hot:
                raise RuntimeError(
                    f"DXX {target_date.isoformat()} 今日热点为空，停止推送"
                )
        return render_article(job, target_date, article, today_hot=today_hot)

    subject_id = SUBJECTS[job]
    cls_client = ClsClient()
    summary = cls_client.find_article_for_date(subject_id, target_date)
    if summary is None:
        return None
    article = cls_client.fetch_detail(summary)
    today_hot = None
    if job in {"focus", "close"}:
        today_hot = DxxClient().today_hot(target_date)
        if not today_hot:
            raise RuntimeError(f"DXX {target_date.isoformat()} 今日热点为空，停止推送")
    return render_article(job, target_date, article, today_hot=today_hot)


def expected_key(job: str, target_date: date) -> str:
    if job == "weekly":
        monday = target_date - timedelta(days=target_date.weekday())
        return f"weekly:{monday.isoformat()}"
    return f"{job}:{target_date.isoformat()}"


def run_job(
    job: str,
    *,
    target_date: date,
    state_path: Path,
    dry_run: bool,
    force: bool,
) -> int:
    if job in GROUPS:
        results: list[int] = []
        for member in GROUPS[job]:
            try:
                result = run_job(
                    member,
                    target_date=target_date,
                    state_path=state_path,
                    dry_run=dry_run,
                    force=force,
                )
            except Exception as exc:
                print(f"{member}: 执行失败，继续扫描其他来源: {exc}", file=sys.stderr)
                result = 2
            results.append(result)
        return 2 if any(result != 0 for result in results) else 0

    channels = None
    channel_ids: list[str] = []
    state = DeliveryState(state_path)
    if not dry_run:
        channels = load_channel_config()
        channel_ids = [str(channel["id"]) for channel in channels]
        state.load()
        key = expected_key(job, target_date)
        if not force and state.all_channels_succeeded(key, channel_ids):
            print(f"{key}: 所有渠道当天已成功，在抓取前停止")
            return 0

    message = build_message(job, target_date)
    if message is None:
        print(f"{job}: {target_date.isoformat()} 暂无匹配内容，不推送")
        return 0

    print(
        f"{job}: 找到内容 {message.source_id}，"
        f"日期 {message.date_key}，标题 {message.title}"
    )
    if dry_run:
        print("\n--- DRY RUN / MARKDOWN ---\n")
        print(message.markdown)
        return 0

    if not force and state.source_succeeded(message.source_id, channel_ids):
        print(f"{job}: 文章 {message.source_id} 已向所有渠道推送，按文章 ID 停止")
        return 0

    digest = str(message.metadata["digest"])
    pending, completed_parts = state.prepare(
        message.key, digest, channel_ids, force=force
    )
    if not pending:
        print(f"{message.key}: 所有渠道均已成功，当天停止推送")
        return 0

    results = push_message(
        message, target_ids=pending, completed_parts=completed_parts
    )
    state.record(
        message.key,
        source_id=message.source_id,
        source_url=message.source_url,
        digest=digest,
        results=results,
        now=datetime.now(BEIJING_TZ),
    )
    state.save()
    failed = [result for result in results if result.get("status") != "success"]
    if failed:
        print(
            "推送存在失败渠道: "
            + ", ".join(str(item.get("id")) for item in failed),
            file=sys.stderr,
        )
        return 2
    print(f"{message.key}: {len(results)} 个渠道推送成功")
    return 0
