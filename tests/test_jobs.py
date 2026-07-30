import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from finance_bot.jobs import build_message, run_job
from finance_bot.models import Message


class JobTests(unittest.TestCase):
    def test_cls_and_jys_jobs_are_enabled_in_automatic_scans(self):
        from finance_bot.jobs import GROUPS, SUBJECTS

        self.assertEqual(SUBJECTS["morning"], 1151)
        self.assertEqual(SUBJECTS["focus"], 1135)
        self.assertEqual(SUBJECTS["close"], 1139)
        self.assertEqual(GROUPS["morning_scan"], ("morning", "pre_market"))
        self.assertEqual(GROUPS["close_scan"], ("focus", "limit_review"))

    def test_group_scan_runs_only_enabled_members(self):
        with tempfile.TemporaryDirectory() as directory, patch(
            "finance_bot.jobs.build_message", return_value=None
        ) as build_message:
            result = run_job(
                "morning_scan",
                target_date=date(2026, 7, 30),
                state_path=Path(directory) / "state.json",
                dry_run=True,
                force=False,
            )
        self.assertEqual(result, 0)
        self.assertEqual(build_message.call_count, 2)
        build_message.assert_any_call("morning", date(2026, 7, 30))
        build_message.assert_any_call("pre_market", date(2026, 7, 30))

    def test_group_scan_continues_after_one_source_fails(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "finance_bot.jobs.GROUPS",
            {"test_scan": ("pre_market", "today_hot")},
        ), patch(
            "finance_bot.jobs.build_message",
            side_effect=(RuntimeError("source down"), None),
        ) as build_message:
            result = run_job(
                "test_scan",
                target_date=date(2026, 7, 30),
                state_path=Path(directory) / "state.json",
                dry_run=True,
                force=False,
            )
        self.assertEqual(result, 2)
        self.assertEqual(build_message.call_count, 2)

    def test_focus_embeds_today_hot(self):
        target_date = date(2026, 7, 30)
        summary = object()
        article = object()
        hot_items = [{"title": "热点", "keyword": "AI", "heat_raw": "1万"}]
        calendar_items = [{"date": "2026-07-30", "event": "财经事件"}]
        with patch("finance_bot.jobs.ClsClient") as cls_client, patch(
            "finance_bot.jobs.DxxClient"
        ) as dxx_client, patch(
            "finance_bot.jobs.render_article", return_value="message"
        ) as render_article:
            cls_client.return_value.find_article_for_date.return_value = summary
            cls_client.return_value.fetch_detail.return_value = article
            dxx_client.return_value.today_hot.return_value = hot_items
            dxx_client.return_value.tomorrow_day_after_calendar.return_value = (
                date(2026, 7, 31),
                date(2026, 8, 1),
                calendar_items,
            )
            result = build_message("focus", target_date)
        self.assertEqual(result, "message")
        render_article.assert_called_once_with(
            "focus",
            target_date,
            article,
            today_hot=hot_items,
            calendar_items=calendar_items,
        )

    def test_limit_review_embeds_today_hot(self):
        target_date = date(2026, 7, 30)
        summary = object()
        article = object()
        hot_items = [{"title": "热点", "keyword": "AI", "heat_raw": "1万"}]
        calendar_items = [{"date": "2026-07-31", "event": "财经事件"}]
        with patch("finance_bot.jobs.JysClient") as jys_client, patch(
            "finance_bot.jobs.DxxClient"
        ) as dxx_client, patch(
            "finance_bot.jobs.render_article", return_value="message"
        ) as render_article:
            jys_client.return_value.find_article_for_date.return_value = summary
            jys_client.return_value.fetch_detail.return_value = article
            dxx_client.return_value.today_hot.return_value = hot_items
            dxx_client.return_value.tomorrow_day_after_calendar.return_value = (
                date(2026, 7, 31),
                date(2026, 8, 1),
                calendar_items,
            )
            result = build_message("limit_review", target_date)
        self.assertEqual(result, "message")
        render_article.assert_called_once_with(
            "limit_review",
            target_date,
            article,
            today_hot=hot_items,
            calendar_items=calendar_items,
        )

    def test_completed_day_stops_before_fetch(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "deliveries": {
                            "close:2026-07-28": {
                                "channels": {"test": {"status": "success"}}
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            config = json.dumps(
                {
                    "channels": [
                        {"id": "test", "name": "DingTalk", "config": {}}
                    ]
                }
            )
            with patch.dict("os.environ", {"ALL_PUSH_CONFIG": config}), patch(
                "finance_bot.jobs.build_message",
                side_effect=AssertionError("不应发生网络抓取"),
            ):
                result = run_job(
                    "close",
                    target_date=date(2026, 7, 28),
                    state_path=state_path,
                    dry_run=False,
                    force=False,
                )
            self.assertEqual(result, 0)

    def test_completed_source_id_stops_before_push(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "deliveries": {
                            "weekend:2026-07-26": {
                                "source_id": "article-42",
                                "channels": {"test": {"status": "success"}},
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            config = json.dumps(
                {
                    "channels": [
                        {"id": "test", "name": "DingTalk", "config": {}}
                    ]
                }
            )
            message = Message(
                key="weekend:2026-07-27",
                feed="weekend",
                date_key="2026-07-27",
                source_id="article-42",
                source_url="https://www.cls.cn/detail/article-42",
                title="same article",
                text="same article",
                markdown="# same article",
                html="<h1>same article</h1>",
                metadata={"digest": "same"},
            )
            with patch.dict("os.environ", {"ALL_PUSH_CONFIG": config}), patch(
                "finance_bot.jobs.build_message", return_value=message
            ), patch("finance_bot.jobs.push_message") as push_message:
                result = run_job(
                    "weekend",
                    target_date=date(2026, 7, 27),
                    state_path=state_path,
                    dry_run=False,
                    force=False,
                )
            self.assertEqual(result, 0)
            push_message.assert_not_called()


if __name__ == "__main__":
    unittest.main()
