"""Cowork vision: annotated screenshots (Set-of-Marks, coordinate grid), who gets them, and image messages."""

import asyncio
import base64
import io
import unittest
from unittest.mock import AsyncMock, MagicMock

from PIL import Image

from emiliano.cowork.agent import CoworkAgentLoop, format_ui_elements, latest_image_only
from emiliano.cowork.vision import (annotated_window_image, draw_grid, draw_marks, encode_for_model,
                                    vision_enabled)
from emiliano.direct.client import to_openai_messages

WHITE = (255, 255, 255)


def window(width=400, height=300):
    return Image.new("RGB", (width, height), WHITE)


class TestDrawing(unittest.TestCase):
    def test_marks_box_elements_in_window_pixels(self):
        tagged = format_ui_elements([{"name": "Save", "role": "Button",
                                      "bounds": {"x": 150, "y": 140, "width": 60, "height": 30}}])
        img = draw_marks(window(), tagged, origin=(100, 100))  # window at screen (100, 100)
        self.assertEqual(img.getpixel((50, 55)), (255, 59, 48))   # left edge of the box at window (50, 40..70)
        self.assertEqual(img.getpixel((80, 55)), WHITE)          # inside the box stays clear

    def test_grid_lines_fall_on_screen_multiples(self):
        img = draw_grid(window(), origin=(250, 120))
        # Screen x=300 is window x=50; screen y=200 is window y=80
        self.assertNotEqual(img.getpixel((50, 150)), WHITE)
        self.assertNotEqual(img.getpixel((150, 80)), WHITE)
        self.assertEqual(img.getpixel((70, 150)), WHITE)

    def test_encode_scales_down(self):
        data = base64.b64decode(encode_for_model(window(2560, 1440)))
        self.assertEqual(Image.open(io.BytesIO(data)).size, (1280, 720))


class TestAnnotatedWindowImage(unittest.TestCase):
    def setUp(self):
        self.pin = MagicMock()
        self.pin.get_window_bounds.return_value = {"x": 10, "y": 20, "width": 400, "height": 300}
        self.perceiver = MagicMock()
        self.perceiver.capture_screenshot.return_value = window()

    def test_marks_when_elements_exist(self):
        tagged = format_ui_elements([{"name": "OK", "role": "Button",
                                      "bounds": {"x": 30, "y": 40, "width": 20, "height": 10}}])
        b64, note = annotated_window_image(self.perceiver, self.pin, 7, tagged)
        self.assertTrue(b64)
        self.assertIn("red box", note)
        self.perceiver.capture_screenshot.assert_called_once_with(bbox=(10, 20, 410, 320))

    def test_grid_when_nothing_detected(self):
        _, note = annotated_window_image(self.perceiver, self.pin, 7, {})
        self.assertIn("click_at", note)

    def test_none_without_a_capturable_window(self):
        self.assertIsNone(annotated_window_image(self.perceiver, self.pin, None, {}))
        self.pin.get_window_bounds.return_value = None
        self.assertIsNone(annotated_window_image(self.perceiver, self.pin, 7, {}))
        self.pin.get_window_bounds.return_value = {"x": 0, "y": 0, "width": 10, "height": 10}
        self.perceiver.capture_screenshot.return_value = MagicMock()  # not an image
        self.assertIsNone(annotated_window_image(self.perceiver, self.pin, 7, {}))


class TestWhoGetsScreenshots(unittest.TestCase):
    def check(self, mode, model, caps, expected):
        mgr = MagicMock()
        mgr.capabilities = AsyncMock(return_value=caps)
        self.assertEqual(asyncio.run(vision_enabled(mode, model, mgr)), expected, (mode, model, caps))

    def test_modes(self):
        self.check("local", "ollama/qwen3.5:2b", ["completion", "vision"], True)
        self.check("local", "ollama/qwen3:4b", ["completion", "tools"], False)
        self.check("local", "anthropic/claude-opus-5-5", [], False)   # the screen never leaves the machine
        self.check("always", "anthropic/claude-opus-5-5", [], True)
        self.check("never", "ollama/qwen3.5:2b", ["vision"], False)


class TestImageMessages(unittest.TestCase):
    def test_openai_conversion(self):
        out = to_openai_messages([{"role": "system", "content": "s"},
                                  {"role": "user", "content": "look", "images": ["AAA"]}])
        self.assertEqual(out[0], {"role": "system", "content": "s"})
        self.assertEqual(out[1]["content"], [{"type": "text", "text": "look"},
                                             {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,AAA"}}])
        self.assertNotIn("images", out[1])

    def test_only_newest_image_is_kept(self):
        history = [{"role": "user", "content": "a", "images": ["1"]}, {"role": "assistant", "content": "b"},
                   {"role": "user", "content": "c", "images": ["2"]}]
        trimmed = latest_image_only(history)
        self.assertNotIn("images", trimmed[0])
        self.assertEqual(trimmed[2]["images"], ["2"])
        self.assertEqual(history[0]["images"], ["1"])  # the original is not changed


class TestLoopAttachesScreenshots(unittest.TestCase):
    def run_loop(self, vision):
        sent = []
        replies = iter(['<call:click_element id="1"/>', "Done."])

        async def stream_completion(messages, **kwargs):
            sent.append(messages)
            yield next(replies)

        client = MagicMock()
        client.stream_completion = stream_completion
        client.last_usage = None
        pin = MagicMock(pinned_hwnd=5, pinned_title="App")
        pin.get_window_bounds.return_value = {"x": 0, "y": 0, "width": 200, "height": 100}
        perceiver = MagicMock()
        perceiver.get_ui_elements.return_value = [{"name": "Go", "role": "Button",
                                                   "bounds": {"x": 10, "y": 10, "width": 40, "height": 20}}]
        perceiver.capture_screenshot.return_value = window(200, 100)
        agent = CoworkAgentLoop(client=client, model_id="ollama/x", pin_manager=pin, screen_perceiver=perceiver,
                                action_synthesizer=MagicMock(), vision=vision)
        asyncio.run(agent.run("press go", hwnd=5))
        return sent

    def test_vision_on(self):
        sent = self.run_loop(vision=True)
        self.assertEqual(len(sent[0][1]["images"]), 1)
        self.assertIn("red box", sent[0][1]["content"])
        second = sent[1]
        self.assertNotIn("images", second[1])          # the first screenshot was dropped...
        self.assertEqual(len(second[-1]["images"]), 1)  # ...for the one taken after the click

    def test_vision_off_sends_text_only(self):
        sent = self.run_loop(vision=False)
        self.assertFalse(any(m.get("images") for call in sent for m in call))


if __name__ == "__main__":
    unittest.main()
