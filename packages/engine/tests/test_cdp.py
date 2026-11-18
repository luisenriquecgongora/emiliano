"""
Unit tests for Chrome DevTools Protocol (CDP) bridge and profile discovery.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from emiliano.cowork.cdp import (
    ChromeDevToolsClient,
    find_chrome_executable,
    list_chrome_profiles,
    is_cdp_available,
)
from emiliano.cowork.agent import CoworkAgentLoop


class TestCDPDiscovery(unittest.TestCase):
    def test_find_chrome_executable(self):
        path = find_chrome_executable()
        if path is not None:
            self.assertTrue(path.lower().endswith("chrome.exe"))

    def test_list_chrome_profiles(self):
        profiles = list_chrome_profiles()
        self.assertIsInstance(profiles, list)

    def test_list_chrome_profiles_with_mock_data(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "Default").mkdir()
            (tmp_path / "Default" / "Preferences").write_text("{}", encoding="utf-8")
            (tmp_path / "Profile 1").mkdir()
            (tmp_path / "Profile 1" / "Preferences").write_text("{}", encoding="utf-8")
            with patch("emiliano.cowork.cdp.get_chrome_user_data_dir", return_value=tmp_path):
                profiles = list_chrome_profiles()
                self.assertIn("Default", profiles)
                self.assertIn("Profile 1", profiles)

    @patch("urllib.request.urlopen")
    def test_is_cdp_available_mock(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        self.assertTrue(is_cdp_available(port=9222))


class TestCDPAgentExecution(unittest.IsolatedAsyncioTestCase):
    async def test_agent_evaluates_js_via_cdp(self):
        mock_client = MagicMock()
        mock_cdp = MagicMock()
        mock_cdp.is_connected = True
        mock_cdp.evaluate = AsyncMock(return_value="https://instagram.com/technoyogapoland")
        mock_cdp.get_page_text = AsyncMock(return_value="Techno Yoga Poland - Warsaw events")

        agent = CoworkAgentLoop(
            client=mock_client,
            model_id="test-model",
            cdp_client=mock_cdp,
        )

        res_eval = await agent.execute_tool("evaluate_js", {"code": "window.location.href"})
        self.assertIn("JavaScript Execution Result: https://instagram.com/technoyogapoland", res_eval)
        mock_cdp.evaluate.assert_called_once_with("window.location.href")

        res_text = await agent.execute_tool("get_page_text", {})
        self.assertIn("Techno Yoga Poland - Warsaw events", res_text)
        mock_cdp.get_page_text.assert_called_once()

    async def test_agent_handles_disconnected_cdp(self):
        mock_client = MagicMock()
        mock_cdp = MagicMock()
        mock_cdp.is_connected = False

        agent = CoworkAgentLoop(
            client=mock_client,
            model_id="test-model",
            cdp_client=mock_cdp,
        )

        res_eval = await agent.execute_tool("evaluate_js", {"code": "window.location.href"})
        self.assertIn("Error: Chrome DevTools Protocol (CDP) client is not connected", res_eval)

    async def test_cdp_client_background_helpers(self):
        import base64
        client = ChromeDevToolsClient()
        client._connected = True
        client._ws = MagicMock()
        client.send_command = AsyncMock(return_value={"data": base64.b64encode(b"fake-png-bytes").decode()})

        # Test screenshot
        shot = await client.capture_screenshot()
        self.assertEqual(shot, b"fake-png-bytes")

        # Test evaluate-based helpers
        client.evaluate = AsyncMock(return_value=True)
        self.assertTrue(await client.click_element("button._acan"))
        self.assertTrue(await client.click_by_text("Message"))
        self.assertTrue(await client.type_into("div[contenteditable='true']", "Hello!"))

        # Test 404 detection
        client.get_page_text = AsyncMock(return_value="Sorry, this page isn't available.")
        self.assertTrue(await client.is_page_404())

        client.get_page_text = AsyncMock(return_value="Restauracja Belvedere Warszawa 120 posts")
        self.assertFalse(await client.is_page_404())
