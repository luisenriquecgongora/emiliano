"""
The Cowork agent shows each target on the desktop HUD overlay before acting on it:
payload shape (checked against the wire protocol model), ordering relative to the
action, failure isolation, and the /api/cowork/run broadcast wiring.
"""

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

import emiliano.cowork.agent as agent_mod
from emiliano.cowork.agent import CoworkAgentLoop, hud_highlight_payload, point_element
from emiliano.server import app as app_mod

_PROTOCOL = Path(__file__).resolve().parents[2] / "protocol" / "models.py"


def _protocol_models():
    spec = importlib.util.spec_from_file_location("emiliano_protocol_models", _PROTOCOL)
    mod = importlib.util.module_from_spec(spec)
    # Registered first: the models use postponed annotations that pydantic resolves by module name
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _agent(synth, on_highlight=None):
    perceiver = MagicMock()
    perceiver.get_ui_elements.return_value = [
        {"name": "Save", "role": "Button", "bounds": {"x": 10, "y": 20, "width": 40, "height": 20}},
        {"name": "Input", "role": "TextInput", "bounds": {"x": 60, "y": 20, "width": 100, "height": 20}},
    ]
    agent = CoworkAgentLoop(
        client=MagicMock(), model_id="test-model",
        pin_manager=MagicMock(pinned_hwnd=100, pinned_title="Test App"),
        screen_perceiver=perceiver, action_synthesizer=synth, on_highlight=on_highlight,
    )
    agent.observe(hwnd=100)
    return agent


class TestHudPayload(unittest.TestCase):
    def test_payload_matches_the_wire_protocol(self):
        el = {"id": 3, "name": "Save", "role": "Button", "bounds": {"x": 10, "y": 20, "width": 40, "height": 20}}
        payload = hud_highlight_payload(el, "click", "Clicking Button 'Save'")
        model = _protocol_models().HUDHighlightPayload.model_validate(payload)
        self.assertEqual(model.element.bounds.width, 40)
        self.assertEqual(payload["element"]["id"], "3")
        self.assertEqual(payload["element"]["action"], "click")

    def test_point_element_centres_a_box_on_the_click(self):
        el = point_element(100, 200)
        b = el["bounds"]
        self.assertEqual((b["x"] + b["width"] // 2, b["y"] + b["height"] // 2), (100, 200))


@patch.object(agent_mod, "HUD_LEAD_SECONDS", 0)
class TestHighlightBeforeAction(unittest.IsolatedAsyncioTestCase):
    async def test_click_is_highlighted_before_it_happens(self):
        events = []
        synth = MagicMock()
        synth.click.side_effect = lambda **kw: events.append(("click", kw))
        agent = _agent(synth, on_highlight=lambda p: events.append(("hud", p)))

        await agent.execute_tool("click_element", {"id": 1}, hwnd=100)

        self.assertEqual([e[0] for e in events], ["hud", "click"])
        element = events[0][1]["element"]
        self.assertEqual(element["name"], "Save")
        self.assertEqual(element["bounds"], {"x": 10, "y": 20, "width": 40, "height": 20})
        self.assertEqual(element["action"], "click")

    async def test_typing_and_click_at_are_highlighted(self):
        seen = []
        agent = _agent(MagicMock(), on_highlight=AsyncMock(side_effect=lambda p: seen.append(p)))

        await agent.execute_tool("type_into_element", {"id": 2, "text": "hi"}, hwnd=100)
        await agent.execute_tool("click_at", {"x": 300, "y": 400}, hwnd=100)

        self.assertEqual(seen[0]["element"]["action"], "type")
        self.assertEqual(seen[0]["element"]["name"], "Input")
        self.assertEqual(seen[1]["element"]["role"], "Point")

    async def test_a_broken_overlay_never_blocks_the_action(self):
        synth = MagicMock()

        def boom(_payload):
            raise RuntimeError("overlay gone")

        agent = _agent(synth, on_highlight=boom)
        result = await agent.execute_tool("click_element", {"id": 1}, hwnd=100)
        self.assertIn("Success", result)
        synth.click.assert_called_once_with(x=30, y=30)

    async def test_no_callback_means_no_highlight(self):
        synth = MagicMock()
        result = await _agent(synth).execute_tool("click_element", {"id": 1}, hwnd=100)
        self.assertIn("Success", result)


class TestRunEndpointBroadcasts(unittest.TestCase):
    def test_highlights_go_to_the_overlay_and_are_cleared_at_the_end(self):
        async def fake_run(self, goal, hwnd=None, **_):
            await self.highlight({"id": 1, "name": "OK", "role": "Button",
                                  "bounds": {"x": 1, "y": 2, "width": 3, "height": 4}}, "click", "why")
            return "done"

        broadcast = AsyncMock()
        with patch.object(app_mod, "broadcast_event", broadcast), \
                patch.object(agent_mod, "HUD_LEAD_SECONDS", 0), \
                patch.object(CoworkAgentLoop, "run", autospec=True, side_effect=fake_run):
            resp = TestClient(app_mod.app, base_url="http://127.0.0.1").post(
                "/api/cowork/run", json={"goal": "Click OK"})

        self.assertEqual(resp.status_code, 200)
        types = [c.args[0] for c in broadcast.await_args_list]
        self.assertEqual(types, ["HUD_HIGHLIGHT", "HUD_CLEAR"])
        self.assertEqual(broadcast.await_args_list[0].args[1]["element"]["name"], "OK")


if __name__ == "__main__":
    unittest.main()
