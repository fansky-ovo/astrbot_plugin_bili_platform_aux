"""Unit tests for the preview card renderer."""

from __future__ import annotations

import io
import unittest

from PIL import Image

import render


def _png(color, size=(300, 500)):
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


class PreviewCardTests(unittest.TestCase):
    def test_clean_text_drops_emoji_and_keeps_text(self):
        cleaned = render.clean_text("嵌：🐷 & 明哲 🎉✨")
        self.assertNotIn("🐷", cleaned)
        self.assertIn("明哲", cleaned)
        self.assertIn("嵌：", cleaned)

    def test_minimal_card(self):
        card = render.render_preview_card(
            {"account_name": "优优家的相簿", "text": "只有一行正文"}
        )
        self.assertEqual(card.size[0], render.CARD_WIDTH)
        self.assertGreater(card.size[1], 120)

    def test_more_content_makes_a_taller_card(self):
        base = render.render_preview_card({"text": "正文"})
        rich = render.render_preview_card(
            {
                "title": "「标题」",
                "account_name": "账号",
                "time_text": "2026年10月7日 19:00",
                "topic": "蔚蓝档案二创",
                "text": "第一行\n第二行\n第三行",
                "footer": "IP属地：江苏",
            }
        )
        self.assertGreater(rich.size[1], base.size[1])

    def test_images_are_composited(self):
        one = render.render_preview_card(
            {"text": "x", "image_bytes": [_png((200, 30, 30))]}
        )
        reds = one.convert("RGB").tobytes()
        self.assertTrue(any(reds[i] > 150 for i in range(0, len(reds), 3)))
        four = render.render_preview_card(
            {"text": "x", "image_bytes": [_png((30, 120, 200))] * 4}
        )
        self.assertEqual(four.size[0], render.CARD_WIDTH)
        self.assertGreater(four.size[1], 400)
        blues = four.convert("RGB").tobytes()
        self.assertTrue(any(blues[i] > 150 for i in range(2, len(blues), 3)))

    def test_text_never_overflows_the_card(self):
        card = render.render_preview_card(
            {
                "title": "标题" * 20,
                "account_name": "很长的账号名字" * 3,
                "text": "正文内容" * 40,
            }
        )
        pixels = card.convert("RGB").load()
        # 卡片本体画到 [MARGIN, CARD_WIDTH-MARGIN]，所以只检查边界之外
        right = card.size[0] - render.MARGIN + 1
        for y in range(render.MARGIN + 1, card.size[1] - render.MARGIN):
            for x in range(right, card.size[0]):
                self.assertEqual(
                    pixels[x, y], render.BG, f"内容溢出到卡片外: ({x},{y})"
                )

    def test_missing_emoji_font_still_renders(self):
        card = render.render_preview_card(
            {
                "text": "嵌：🐷 & 明哲",
                "emoji_font_path": "/nope/NotoColorEmoji.ttf",
            }
        )
        self.assertEqual(card.size[0], render.CARD_WIDTH)

    def test_broken_image_bytes_are_ignored(self):
        card = render.render_preview_card(
            {"text": "x", "image_bytes": [b"not-an-image"]}
        )
        self.assertEqual(card.size[0], render.CARD_WIDTH)

    def test_very_tall_image_is_capped(self):
        tall = _png((10, 10, 10), size=(400, 4000))
        card = render.render_preview_card({"text": "x", "image_bytes": [tall]})
        self.assertLess(card.size[1], 2200)


if __name__ == "__main__":
    unittest.main()
