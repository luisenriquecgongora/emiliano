"""
Unit tests for Emiliano Desktop Cowork module:
Window pinning, action synthesis guardrails, and screen perception.
"""

import unittest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from emiliano.cowork import WindowPinManager, ActionSynthesizer, SafetyInterruptedError
from emiliano.server.app import app


class TestWindowPinManager(unittest.TestCase):
    def setUp(self):
        self.mgr = WindowPinManager()

    def test_pin_and_unpin(self):
        self.assertFalse(self.mgr.is_pinned())
        self.mgr.pin(12345, "Test Application")
        self.assertTrue(self.mgr.is_pinned())
        self.assertEqual(self.mgr.pinned_hwnd, 12345)
        self.assertEqual(self.mgr.pinned_title, "Test Application")

        self.mgr.unpin()
        self.assertFalse(self.mgr.is_pinned())
        self.assertIsNone(self.mgr.pinned_hwnd)

    def test_bounds_check_when_unpinned(self):
        # Unpinned allows any coordinate
        self.assertTrue(self.mgr.is_point_within_pinned_window(500, 500))

    def test_bounds_check_when_pinned(self):
        self.mgr.pin(12345, "Test Application")
        with patch.object(self.mgr, "get_window_bounds", return_value={"x": 100, "y": 100, "width": 800, "height": 600}):
            # Inside bounds
            self.assertTrue(self.mgr.is_point_within_pinned_window(200, 200))
            self.assertTrue(self.mgr.is_point_within_pinned_window(100, 100))
            self.assertTrue(self.mgr.is_point_within_pinned_window(900, 700))
            # Outside bounds
            self.assertFalse(self.mgr.is_point_within_pinned_window(50, 50))
            self.assertFalse(self.mgr.is_point_within_pinned_window(950, 200))


class TestActionSynthesizer(unittest.TestCase):
    def setUp(self):
        self.pin_mgr = WindowPinManager()
        self.synth = ActionSynthesizer(pin_manager=self.pin_mgr)
        self.synth.preview_delay_seconds = 0.0  # Zero delay for unit tests

    def test_paused_aborts_click(self):
        self.synth.set_paused(True)
        with self.assertRaises(SafetyInterruptedError):
            self.synth.click(100, 100)

    def test_paused_aborts_type(self):
        self.synth.set_paused(True)
        with self.assertRaises(SafetyInterruptedError):
            self.synth.type_text("test")

    def test_out_of_bounds_click_rejected(self):
        self.pin_mgr.pin(999, "Pinned App")
        with patch.object(self.pin_mgr, "is_point_within_pinned_window", return_value=False):
            with self.assertRaises(SafetyInterruptedError):
                self.synth.click(50, 50)

    @patch("emiliano.cowork.actions._pyautogui")
    def test_safe_click_executed(self, mock_gui):
        with patch.object(self.pin_mgr, "verify_active", return_value=True):
            with patch.object(self.pin_mgr, "is_point_within_pinned_window", return_value=True):
                self.synth.click(200, 300, button="left")
                mock_gui.return_value.moveTo.assert_called_once_with(200, 300, duration=0.15)
                mock_gui.return_value.click.assert_called_once_with(x=200, y=300, button="left", clicks=1)

    @patch("emiliano.cowork.actions._pyautogui")
    def test_ghost_click_invoked_without_cursor_movement(self, mock_gui):
        mock_uia = MagicMock()
        mock_uia.available = True
        mock_uia.invoke_at.return_value = True

        synth = ActionSynthesizer(pin_manager=self.pin_mgr, uia_reader=mock_uia, ghost_mode=True)
        synth.preview_delay_seconds = 0.0

        with patch.object(self.pin_mgr, "verify_active", return_value=True):
            with patch.object(self.pin_mgr, "is_point_within_pinned_window", return_value=True):
                synth.click(200, 300, button="left")
                mock_uia.invoke_at.assert_called_once_with(200, 300)
                mock_gui.return_value.moveTo.assert_not_called()
                mock_gui.return_value.click.assert_not_called()

    @patch("emiliano.cowork.actions._pyautogui")
    def test_ghost_click_falls_back_when_invoke_fails(self, mock_gui):
        mock_uia = MagicMock()
        mock_uia.available = True
        mock_uia.invoke_at.return_value = False

        synth = ActionSynthesizer(pin_manager=self.pin_mgr, uia_reader=mock_uia, ghost_mode=True)
        synth.preview_delay_seconds = 0.0

        with patch.object(self.pin_mgr, "verify_active", return_value=True):
            with patch.object(self.pin_mgr, "is_point_within_pinned_window", return_value=True):
                synth.click(200, 300, button="left")
                mock_uia.invoke_at.assert_called_once_with(200, 300)
                mock_gui.return_value.moveTo.assert_called_once_with(200, 300, duration=0.15)
                mock_gui.return_value.click.assert_called_once_with(x=200, y=300, button="left", clicks=1)

    @patch("emiliano.cowork.actions._pyautogui")
    def test_ghost_type_without_synthetic_keystrokes(self, mock_gui):
        mock_uia = MagicMock()
        mock_uia.available = True
        mock_uia.set_value_at.return_value = True

        synth = ActionSynthesizer(pin_manager=self.pin_mgr, uia_reader=mock_uia, ghost_mode=True)
        synth.preview_delay_seconds = 0.0

        with patch.object(self.pin_mgr, "verify_active", return_value=True):
            with patch.object(self.pin_mgr, "is_point_within_pinned_window", return_value=True):
                synth.type_text("hello ghost", x=150, y=250)
                mock_uia.set_value_at.assert_called_once_with(150, 250, "hello ghost")
                mock_gui.return_value.typewrite.assert_not_called()

    @patch("emiliano.cowork.actions._pyautogui")
    def test_ghost_type_falls_back_when_set_value_fails(self, mock_gui):
        mock_uia = MagicMock()
        mock_uia.available = True
        mock_uia.set_value_at.return_value = False

        synth = ActionSynthesizer(pin_manager=self.pin_mgr, uia_reader=mock_uia, ghost_mode=True)
        synth.preview_delay_seconds = 0.0

        with patch.object(self.pin_mgr, "verify_active", return_value=True):
            with patch.object(self.pin_mgr, "is_point_within_pinned_window", return_value=True):
                synth.type_text("fallback text", x=150, y=250)
                mock_uia.set_value_at.assert_called_once_with(150, 250, "fallback text")
                mock_gui.return_value.typewrite.assert_called_once_with("fallback text", interval=0.02)


class TestCoworkApi(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app, base_url="http://127.0.0.1")

    def test_list_windows(self):
        resp = self.client.get("/api/cowork/windows")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("windows", resp.json())
        self.assertIsInstance(resp.json()["windows"], list)

    def test_pin_and_unpin_endpoints(self):
        pin_resp = self.client.post("/api/cowork/pin", json={"hwnd": 8888, "title": "Editor"})
        self.assertEqual(pin_resp.status_code, 200)
        self.assertEqual(pin_resp.json()["status"], "pinned")
        self.assertEqual(pin_resp.json()["hwnd"], 8888)

        unpin_resp = self.client.post("/api/cowork/unpin")
        self.assertEqual(unpin_resp.status_code, 200)
        self.assertEqual(unpin_resp.json()["status"], "unpinned")

    def test_get_elements(self):
        resp = self.client.get("/api/cowork/elements")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("elements", resp.json())


if __name__ == "__main__":
    unittest.main()
