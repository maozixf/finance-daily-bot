from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any


class DeliveryState:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: dict[str, Any] = {"schema_version": 1, "deliveries": {}}

    def load(self) -> None:
        if not self.path.exists():
            return
        loaded = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict) or not isinstance(
            loaded.get("deliveries"), dict
        ):
            raise ValueError(f"状态文件格式错误: {self.path}")
        self.data = loaded

    def prepare(
        self,
        key: str,
        digest: str,
        channel_ids: list[str],
        *,
        force: bool = False,
    ) -> tuple[list[str], dict[str, list[int]]]:
        deliveries = self.data.setdefault("deliveries", {})
        entry = deliveries.get(key)
        if not isinstance(entry, dict):
            entry = {"message_digest": digest, "channels": {}}
            deliveries[key] = entry
        elif entry.get("message_digest") != digest:
            previous_channels = entry.get("channels", {})
            successful = {
                channel_id: channel
                for channel_id, channel in previous_channels.items()
                if isinstance(channel, dict) and channel.get("status") == "success"
            }
            entry = {"message_digest": digest, "channels": successful}
            deliveries[key] = entry
        channels = entry.setdefault("channels", {})
        if force:
            channels.clear()

        pending: list[str] = []
        completed_parts: dict[str, list[int]] = {}
        for channel_id in channel_ids:
            channel = channels.get(channel_id, {})
            if channel.get("status") == "success":
                continue
            pending.append(channel_id)
            completed_parts[channel_id] = [
                int(index) for index in channel.get("completed_parts", [])
            ]
        return pending, completed_parts

    def all_channels_succeeded(self, key: str, channel_ids: list[str]) -> bool:
        entry = self.data.get("deliveries", {}).get(key)
        if not isinstance(entry, dict):
            return False
        channels = entry.get("channels", {})
        return bool(channel_ids) and all(
            isinstance(channels.get(channel_id), dict)
            and channels[channel_id].get("status") == "success"
            for channel_id in channel_ids
        )

    def source_succeeded(self, source_id: str, channel_ids: list[str]) -> bool:
        if not source_id or not channel_ids:
            return False
        for entry in self.data.get("deliveries", {}).values():
            if not isinstance(entry, dict) or str(entry.get("source_id")) != source_id:
                continue
            channels = entry.get("channels", {})
            if all(
                isinstance(channels.get(channel_id), dict)
                and channels[channel_id].get("status") == "success"
                for channel_id in channel_ids
            ):
                return True
        return False

    def record(
        self,
        key: str,
        *,
        source_id: str,
        source_url: str,
        digest: str,
        results: list[dict[str, Any]],
        now: datetime,
    ) -> None:
        deliveries = self.data.setdefault("deliveries", {})
        entry = deliveries.setdefault(key, {})
        if entry.get("message_digest") != digest:
            entry.clear()
        entry.update(
            {
                "source_id": source_id,
                "source_url": source_url,
                "message_digest": digest,
                "updated_at": now.isoformat(),
            }
        )
        channels = entry.setdefault("channels", {})
        for result in results:
            channel_id = str(result.get("id") or "")
            if not channel_id:
                continue
            channels[channel_id] = {
                "status": result.get("status", "failed"),
                "completed_parts": result.get("completed_parts", []),
                "parts_total": result.get("parts_total", 0),
                "updated_at": now.isoformat(),
                "error": result.get("error"),
            }

    def prune(self, keep: int = 2000) -> None:
        deliveries = self.data.setdefault("deliveries", {})
        if len(deliveries) <= keep:
            return
        ordered = sorted(
            deliveries.items(),
            key=lambda pair: str(pair[1].get("updated_at", "")),
            reverse=True,
        )
        self.data["deliveries"] = dict(ordered[:keep])

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.prune()
        payload = json.dumps(self.data, ensure_ascii=False, indent=2) + "\n"
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self.path.parent,
            prefix=self.path.name + ".",
            delete=False,
        ) as handle:
            handle.write(payload)
            temporary = Path(handle.name)
        os.replace(temporary, self.path)
