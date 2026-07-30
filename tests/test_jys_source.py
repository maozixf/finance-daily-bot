import json
import unittest
from datetime import date

from finance_bot.jys_source import (
    JysClient,
    parse_nuxt_article_content,
    parse_profile_articles,
)


PROFILE_HTML = """
<html><body>
  <div class="community-bar"><ul><li>
    <div class="fs13-ash">2026-07-30 07:02:52</div>
    <div class="book-title click fs17-bold"><span>7月30日盘前纪要</span></div>
    <div class="html-text">
      <a href="/a/article42"><span>文章摘要</span></a>
    </div>
  </li></ul></div>
</body></html>
"""


def detail_html(content: str) -> str:
    encoded = json.dumps(content, ensure_ascii=False)
    return (
        "<html><script>"
        "window.__NUXT__=(function(){return {data:[{data:{"
        f'content:{encoded}'
        "}}]}})();"
        "</script></html>"
    )


class FakeJysClient(JysClient):
    def _get(self, url):
        if "/u/" in url:
            return PROFILE_HTML
        return detail_html(
            '<p><strong>正文</strong></p>'
            '<p><img src="https://image.example/body.png"></p>'
        )


class JysSourceTests(unittest.TestCase):
    def test_profile_parser_extracts_article_metadata(self):
        articles = parse_profile_articles(
            PROFILE_HTML,
            user_id="user42",
            author="盘前纪要",
            subject_name="盘前纪要",
        )
        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0].article_id, "article42")
        self.assertEqual(articles[0].title, "7月30日盘前纪要")
        self.assertEqual(articles[0].brief, "文章摘要")
        self.assertEqual(articles[0].source_label, "韭研公社原文")

    def test_parse_nuxt_content_decodes_escaped_html(self):
        content = '<p>正文</p><img src="https://image.example/body.png">'
        self.assertEqual(parse_nuxt_article_content(detail_html(content)), content)

    def test_find_and_fetch_detail(self):
        client = FakeJysClient()
        summary = client.find_article_for_date(
            user_id="user42",
            author="盘前纪要",
            subject_name="盘前纪要",
            title_terms=("盘前纪要",),
            target_date=date(2026, 7, 30),
        )
        self.assertIsNotNone(summary)
        detail = client.fetch_detail(summary)
        self.assertEqual(detail.article_id, "article42")
        self.assertEqual(detail.images, ("https://image.example/body.png",))
        self.assertIn("<strong>正文</strong>", detail.content_html)

    def test_missing_nuxt_payload_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "window.__NUXT__"):
            parse_nuxt_article_content("<html></html>")

    def test_empty_profile_is_rejected(self):
        client = FakeJysClient()
        client._get = lambda url: "<html></html>"
        with self.assertRaisesRegex(ValueError, "未解析到文章"):
            client.fetch_profile(
                user_id="user42",
                author="盘前纪要",
                subject_name="盘前纪要",
            )


if __name__ == "__main__":
    unittest.main()
