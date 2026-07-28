from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .cls_source import ClsClient
from .delivery import load_channel_config, push_message
from .dxx_source import DxxClient
from .models import Message
from .render import render_article, render_calendar
from .state import DeliveryState


BEIJING_TZ = ZoneInfo("Asia/Shanghai")
SUBJECTS = {
    "morning": 1151,
    "focus": 1135,
    # Retained for manual use only; no scheduled workflow calls this job.
    "close": 1139,
    "weekend": 12471,
}


def build_message(job: str, target_date: date) -> Message | None:
    if job == "weekly":
        start, end, items = DxxClient().two_week_calendar(target_date)
        if not items:
            return None
        return render_calendar(start, end, items)

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
