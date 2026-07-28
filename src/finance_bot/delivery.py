from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .models import Message


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_channel_config(raw: str | None = None) -> list[dict[str, Any]]:
    value = raw if raw is not None else os.environ.get("ALL_PUSH_CONFIG", "")
    if not value.strip():
        raise ValueError("缺少 ALL_PUSH_CONFIG")
    parsed = json.loads(value)
    channels = parsed.get("channels") if isinstance(parsed, dict) else parsed
    if not isinstance(channels, list) or not channels:
        raise ValueError("ALL_PUSH_CONFIG 必须是非空渠道数组或包含 channels 数组")
    seen: set[str] = set()
    for channel in channels:
        if not isinstance(channel, dict):
            raise ValueError("推送渠道配置必须是对象")
        channel_id = str(channel.get("id") or "").strip()
        if not channel_id or channel_id in seen:
            raise ValueError("每个推送渠道必须有唯一 id")
        if not channel.get("name") or not isinstance(channel.get("config"), dict):
            raise ValueError(f"渠道 {channel_id} 缺少 name/config")
        seen.add(channel_id)
    return channels


def push_message(
    message: Message,
    *,
    target_ids: list[str],
    completed_parts: dict[str, list[int]],
) -> list[dict[str, Any]]:
    payload = {
        "title": message.title,
        "text": message.text,
        "markdown": message.markdown,
        "html": message.html,
        "target_ids": target_ids,
        "completed_parts": completed_parts,
    }
    script = PROJECT_ROOT / "scripts" / "push.mjs"
    if not script.exists():
        raise FileNotFoundError(script)

    with tempfile.TemporaryDirectory(prefix="finance-bot-") as directory:
        payload_path = Path(directory) / "payload.json"
        result_path = Path(directory) / "result.json"
        payload_path.write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
        process = subprocess.run(
            [
                "node",
                str(script),
                "--payload",
                str(payload_path),
                "--result",
                str(result_path),
            ],
            cwd=PROJECT_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if process.stdout:
            print(process.stdout.rstrip())
        if not result_path.exists():
            raise RuntimeError(
                f"推送进程未生成结果文件，退出码 {process.returncode}"
            )
        results = json.loads(result_path.read_text(encoding="utf-8"))
        if not isinstance(results, list):
            raise ValueError("推送结果必须是数组")
        return results
