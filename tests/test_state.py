import tempfile
import unittest
from pathlib import Path

from finance_bot.state import DeliveryState


class DeliveryStateTests(unittest.TestCase):
    def test_successful_channel_is_once_per_date_even_if_digest_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            state = DeliveryState(Path(directory) / "state.json")
            pending, _ = state.prepare("close:2026-07-28", "digest-a", ["a", "b"])
            self.assertEqual(pending, ["a", "b"])
            state.data["deliveries"]["close:2026-07-28"]["channels"] = {
                "a": {"status": "success", "completed_parts": [0]},
                "b": {"status": "failed", "completed_parts": [0]},
            }
            pending, completed = state.prepare(
                "close:2026-07-28", "digest-b", ["a", "b"]
            )
            self.assertEqual(pending, ["b"])
            self.assertEqual(completed["b"], [])

    def test_force_reenables_successful_channel(self):
        state = DeliveryState(Path("unused.json"))
        state.data["deliveries"] = {
            "morning:2026-07-28": {
                "message_digest": "x",
                "channels": {"a": {"status": "success"}},
            }
        }
        pending, _ = state.prepare(
            "morning:2026-07-28", "x", ["a"], force=True
        )
        self.assertEqual(pending, ["a"])

    def test_all_channels_succeeded_requires_every_configured_channel(self):
        state = DeliveryState(Path("unused.json"))
        state.data["deliveries"] = {
            "weekend:2026-07-26": {
                "channels": {"a": {"status": "success"}}
            }
        }
        self.assertTrue(
            state.all_channels_succeeded("weekend:2026-07-26", ["a"])
        )
        self.assertFalse(
            state.all_channels_succeeded("weekend:2026-07-26", ["a", "b"])
        )

    def test_source_succeeded_deduplicates_article_across_dates(self):
        state = DeliveryState(Path("unused.json"))
        state.data["deliveries"] = {
            "weekend:2026-07-26": {
                "source_id": "article-42",
                "channels": {
                    "a": {"status": "success"},
                    "b": {"status": "success"},
                },
            }
        }
        self.assertTrue(state.source_succeeded("article-42", ["a", "b"]))
        self.assertFalse(state.source_succeeded("article-42", ["a", "b", "c"]))
        self.assertFalse(state.source_succeeded("article-43", ["a", "b"]))


if __name__ == "__main__":
    unittest.main()
