from __future__ import annotations

import argparse
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .jobs import run_job


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("日期必须是 YYYY-MM-DD") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="财联社 + DXX 财经定时推送机器人")
    parser.add_argument(
        "--job",
        required=True,
        choices=("morning", "focus", "close", "weekly", "weekend"),
    )
    parser.add_argument("--date", type=_parse_date, help="北京时间日期，默认今天")
    parser.add_argument(
        "--state-file", type=Path, default=Path("state/deliveries.json")
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="忽略已有推送状态")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    target_date = args.date or datetime.now(ZoneInfo("Asia/Shanghai")).date()
    return run_job(
        args.job,
        target_date=target_date,
        state_path=args.state_file,
        dry_run=args.dry_run,
        force=args.force,
    )


if __name__ == "__main__":
    raise SystemExit(main())
