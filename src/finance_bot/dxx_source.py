from __future__ import annotations

from datetime import date, timedelta
import time
from typing import Any

from .dxx_hot_focus import SECTIONS, fetch_section


SPEC_BY_KEY = {spec.key: spec for spec in SECTIONS}


class DxxClient:
    def __init__(self, timeout: float = 20.0) -> None:
        self.timeout = timeout

    def _fetch(self, key: str) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                return fetch_section(
                    SPEC_BY_KEY[key], timeout=self.timeout, limit=0
                )
            except Exception as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(1 << attempt)
        raise RuntimeError(f"DXX {key} 请求失败（已重试 3 次）") from last_error

    def today_hot(self, target_date: date) -> list[dict[str, Any]]:
        section = self._fetch("today_hot")
        items = [
            item
            for item in section.get("items", [])
            if item.get("date") == target_date.isoformat()
        ]
        return items

    def calendar_range(
        self, start: date, end: date
    ) -> list[dict[str, Any]]:
        section = self._fetch("finance_calendar")
        items: list[dict[str, Any]] = []
        for item in section.get("items", []):
            try:
                item_date = date.fromisoformat(str(item.get("date")))
            except (TypeError, ValueError):
                continue
            if start <= item_date <= end:
                items.append(item)
        return items

    def tomorrow_day_after_calendar(
        self, target_date: date
    ) -> tuple[date, date, list[dict[str, Any]]]:
        start = target_date + timedelta(days=1)
        end = target_date + timedelta(days=2)
        return start, end, self.calendar_range(start, end)

    def two_week_calendar(
        self, any_date_in_week: date
    ) -> tuple[date, date, list[dict[str, Any]]]:
        start = any_date_in_week - timedelta(days=any_date_in_week.weekday())
        end = start + timedelta(days=13)
        return start, end, self.calendar_range(start, end)
