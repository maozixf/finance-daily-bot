import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from finance_bot.jobs import run_job
from finance_bot.models import Message


class JobTests(unittest.TestCase):
    def test_subject_mapping_keeps_manual_review_and_activates_focus_review(self):
        from finance_bot.jobs import SUBJECTS

        self.assertEqual(SUBJECTS["focus"], 1135)
        self.assertEqual(SUBJECTS["close"], 1139)

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
