"""
Unit tests for the autonomous CoworkAgentLoop:
Set-of-Marks UI element grounding, tool parsing, perception-action loop execution,
and /api/cowork/run endpoint.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from emiliano.cowork.agent import (
    CoworkAgentLoop,
    format_ui_elements,
    parse_cowork_tool_calls,
    render_elements_text,
)
from emiliano.server.app import app


class TestCoworkAgentGrounding(unittest.TestCase):
    def test_format_and_render_elements(self):
        raw = [
            {
                "hwnd": 100,
                "name": "Submit",
                "role": "Button",
                "action": "click",
                "bounds": {"x": 50, "y": 60, "width": 80, "height": 30},
            },
            {
                "hwnd": 100,
                "name": "Search Box",
                "role": "TextInput",
                "action": "type",
                "bounds": {"x": 200, "y": 60, "width": 150, "height": 30},
            },
        ]

        tagged = format_ui_elements(raw)
        self.assertEqual(len(tagged), 2)
        self.assertEqual(tagged[1]["name"], "Submit")
        self.assertEqual((tagged[1]["cx"], tagged[1]["cy"]), (90, 75))
        self.assertEqual(tagged[2]["name"], "Search Box")
        self.assertEqual((tagged[2]["cx"], tagged[2]["cy"]), (275, 75))

        rendered = render_elements_text(tagged)
        self.assertIn("[1] Button \"Submit\" at (90, 75)", rendered)
        self.assertIn("[2] TextInput \"Search Box\" at (275, 75)", rendered)

    def test_parse_tool_calls_xml(self):
        text = 'I will click submit.\n<call:click_element id="1"/>'
        calls = parse_cowork_tool_calls(text)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["tool"], "click_element")
        self.assertEqual(calls[0]["args"], {"id": 1})

    def test_parse_tool_calls_json(self):
        text = 'Thinking...\n<tool_call>\n{"name": "type_into_element", "arguments": {"id": 2, "text": "theme"}}\n</tool_call>'
        calls = parse_cowork_tool_calls(text)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["tool"], "type_into_element")
        self.assertEqual(calls[0]["args"], {"id": 2, "text": "theme"})


class TestCoworkAgentExecution(unittest.IsolatedAsyncioTestCase):
    async def test_execute_click_and_type_tools(self):
        mock_client = MagicMock()
        mock_pin = MagicMock(pinned_hwnd=100, pinned_title="Test App")
        mock_perceiver = MagicMock()
        mock_perceiver.get_ui_elements.return_value = [
            {"name": "Save", "role": "Button", "bounds": {"x": 10, "y": 20, "width": 40, "height": 20}},
            {"name": "Input", "role": "TextInput", "bounds": {"x": 60, "y": 20, "width": 100, "height": 20}},
        ]
        mock_synth = MagicMock()

        agent = CoworkAgentLoop(
            client=mock_client,
            model_id="test-model",
            pin_manager=mock_pin,
            screen_perceiver=mock_perceiver,
            action_synthesizer=mock_synth,
        )

        agent.observe(hwnd=100)

        # Test click_element
        res_click = await agent.execute_tool("click_element", {"id": 1}, hwnd=100)
        self.assertIn("Success: Clicked Button 'Save'", res_click)
        mock_synth.click.assert_called_once_with(x=30, y=30)

        # Test type_into_element
        res_type = await agent.execute_tool("type_into_element", {"id": 2, "text": "foobar"}, hwnd=100)
        self.assertIn("Success: Typed 'foobar' into TextInput 'Input'", res_type)
        mock_synth.type_text.assert_called_once_with(text="foobar", x=110, y=30)

    async def test_agent_run_loop(self):
        mock_client = MagicMock()

        async def fake_stream(*args, **kwargs):
            # Turn 1: model calls click_element
            # Turn 2: model calls finish
            history = kwargs.get("messages", [])
            if len(history) <= 2:
                yield '<call:click_element id="1"/>'
            else:
                yield '<call:finish summary="Clicked the button and verified"/>'

        mock_client.stream_completion = fake_stream
        mock_client.last_usage = {"prompt_tokens": 10, "completion_tokens": 5}

        mock_pin = MagicMock(pinned_hwnd=100, pinned_title="Test App")
        mock_perceiver = MagicMock()
        mock_perceiver.get_ui_elements.return_value = [
            {"name": "OK", "role": "Button", "bounds": {"x": 0, "y": 0, "width": 50, "height": 20}},
        ]
        mock_synth = MagicMock()

        agent = CoworkAgentLoop(
            client=mock_client,
            model_id="test-model",
            pin_manager=mock_pin,
            screen_perceiver=mock_perceiver,
            action_synthesizer=mock_synth,
            max_turns=3,
        )

        output = await agent.run(goal="Click OK button")
        self.assertIn("click_element", output)
        self.assertIn("finish", output)
        mock_synth.click.assert_called_once_with(x=25, y=10)


class TestCoworkRunEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app, base_url="http://127.0.0.1")

    @patch.object(CoworkAgentLoop, "run", new_callable=AsyncMock)
    def test_run_endpoint_executes_goal(self, mock_run):
        mock_run.return_value = "Task completed successfully"

        resp = self.client.post("/api/cowork/run", json={"goal": "Click settings"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "completed")
        self.assertEqual(data["output"], "Task completed successfully")
