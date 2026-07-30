import unittest
from datetime import date, datetime
from zoneinfo import ZoneInfo

from finance_bot.models import ArticleDetail
from finance_bot.render import render_article, render_calendar, render_today_hot


class RenderTests(unittest.TestCase):
    def test_article_renders_image_audio_and_hot_items(self):
        article = ArticleDetail(
            article_id="42",
            subject_id=1151,
            subject_name="有声早报",
            title="标题",
            brief="摘要",
            author="财联社",
            published_at=datetime(2026, 7, 28, 7, tzinfo=ZoneInfo("Asia/Shanghai")),
            cover_image="https://example/cover.jpg",
            url="https://www.cls.cn/detail/42",
            audio_url="https://example/audio.mp3",
            content_html=(
                "<p><strong>市场表现</strong></p><p>正文第一段。</p>"
                '<p><img src="https://example/body.png" alt="走势图"></p>'
            ),
            images=(),
            source_label="财联社原文",
        )
        message = render_article(
            "close",
            article.published_at.date(),
            article,
            today_hot=[{"title": "热点", "keyword": "AI", "heat_raw": "1万"}],
            calendar_items=[
                {"date": "2026-07-29", "event": "明日第一项"},
                {"date": "2026-07-29", "event": "明日第二项"},
                {"date": "2026-07-30", "event": "后天第一项"},
            ],
        )
        self.assertIn("![走势图](https://example/body.png)", message.markdown)
        self.assertIn('<img src="https://example/body.png"', message.html)
        self.assertIn('name="viewport"', message.html)
        self.assertIn("-webkit-text-size-adjust:100%", message.html)
        self.assertIn("max-width:100%;height:auto", message.html)
        self.assertIn("font-size:17px", message.html)
        self.assertNotIn("https://example/cover.jpg", message.markdown)
        self.assertIn("**市场表现**", message.markdown)
        self.assertIn("正文第一段", message.text)
        self.assertIn("[点击播放](https://example/audio.mp3)", message.markdown)
        self.assertNotIn("### 原文", message.markdown)
        self.assertNotIn("<h3>原文</h3>", message.html)
        self.assertIn("[财联社原文](https://www.cls.cn/detail/42)", message.markdown)
        self.assertLess(
            message.markdown.index("音频链接："),
            message.markdown.index("**市场表现**"),
        )
        self.assertIn("2026-07-28 · 今日热点", message.markdown)
        self.assertIn("热度值：1万", message.markdown)
        self.assertIn("明后天财经日历", message.markdown)
        self.assertIn("明日第一项", message.markdown)
        self.assertIn("后天第一项", message.markdown)
        self.assertLess(
            message.markdown.index("2026-07-28 · 今日热点"),
            message.markdown.index("明后天财经日历"),
        )
        self.assertLess(
            message.markdown.index("明日第一项"),
            message.markdown.index("明日第二项"),
        )

    def test_calendar_preserves_source_date_and_event_order(self):
        message = render_calendar(
            date(2026, 7, 27),
            date(2026, 8, 9),
            [
                {"date": "2026-07-29", "event": "原文第一项"},
                {"date": "2026-07-29", "event": "原文第二项"},
                {"date": "2026-07-28", "event": "原文第三项"},
            ],
        )
        self.assertLess(
            message.markdown.index("2026-07-29"),
            message.markdown.index("2026-07-28"),
        )
        self.assertLess(
            message.markdown.index("原文第一项"),
            message.markdown.index("原文第二项"),
        )
        self.assertIn('name="viewport"', message.html)
        self.assertIn("max-width:680px", message.html)

    def test_limit_review_uses_normalized_title(self):
        article = ArticleDetail(
            article_id="review-1",
            subject_id=0,
            subject_name="连板复盘",
            title="2026 年 7 月 29 日连板个股复盘",
            brief="摘要",
            author="韭研作者",
            published_at=datetime(
                2026, 7, 29, 22, tzinfo=ZoneInfo("Asia/Shanghai")
            ),
            cover_image=None,
            url="https://www.jiuyangongshe.com/a/review-1",
            source_label="韭研公社原文",
        )
        message = render_article("limit_review", date(2026, 7, 29), article)
        self.assertEqual(message.title, "2026-07-29 · 连板个股复盘")
        self.assertIn("# 2026-07-29 · 连板个股复盘", message.markdown)
        self.assertNotIn("2026 年 7 月 29 日", message.markdown)

    def test_today_hot_renders_every_item(self):
        message = render_today_hot(
            date(2026, 7, 30),
            [
                {"title": "热点一", "keyword": "AI", "heat_raw": "68.8万"},
                {"title": "热点二", "keyword": "芯片", "heat_raw": "20万"},
            ],
        )
        self.assertEqual(message.key, "today_hot:2026-07-30")
        self.assertIn("2026-07-30 · 今日热点", message.title)
        self.assertIn("热点一", message.markdown)
        self.assertIn("热点二", message.markdown)
        self.assertLess(message.markdown.index("热点一"), message.markdown.index("热点二"))


if __name__ == "__main__":
    unittest.main()
