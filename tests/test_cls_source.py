import json
import unittest
from datetime import date

from finance_bot.cls_source import ClsClient, parse_next_data


def next_page(page_props):
    payload = json.dumps({"props": {"pageProps": page_props}}, ensure_ascii=False)
    return f'<html><script id="__NEXT_DATA__" type="application/json">{payload}</script></html>'


class FakeClsClient(ClsClient):
    def _get(self, url):
        if "/subject/1151" in url:
            return next_page(
                {
                    "data": {
                        "name": "有声早报",
                        "articles": [
                            {
                                "article_id": 101,
                                "article_title": "测试早报",
                                "article_brief": "第一条\n第二条",
                                "article_author": "财联社",
                                "article_img": "https://image.example/cover.jpg",
                                "article_time": 1785193200,
                            }
                        ],
                    }
                }
            )
        return next_page(
            {
                "articleDetail": {
                    "title": "测试早报",
                    "brief": "第一条\n第二条",
                    "author": "财联社",
                    "content": '<p><img src="https://image.example/body.png"></p>',
                    "images": ["https://image.example/cover.jpg"],
                    "audioUrl": "https://image.example/audio.mp3",
                }
            }
        )


class ClsSourceTests(unittest.TestCase):
    def test_parse_next_data_rejects_missing_script(self):
        with self.assertRaisesRegex(ValueError, "__NEXT_DATA__"):
            parse_next_data("<html></html>")

    def test_find_and_fetch_detail(self):
        client = FakeClsClient()
        summary = client.find_article_for_date(1151, date(2026, 7, 28))
        self.assertIsNotNone(summary)
        detail = client.fetch_detail(summary)
        self.assertEqual(detail.article_id, "101")
        self.assertEqual(detail.audio_url, "https://image.example/audio.mp3")
        self.assertEqual(detail.images, ())
        self.assertIn("body.png", detail.content_html)


if __name__ == "__main__":
    unittest.main()
