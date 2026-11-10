"""
Tests for UI Automation perception (emiliano/cowork/uia.py) and its use in ScreenPerceiver.
Unit tests use fake UIA objects; set EMILIANO_LIVE_UI_TESTS=1 on Windows to also read the real taskbar.
"""

import os
import sys
import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from emiliano.cowork import uia
from emiliano.cowork.uia import UiaReader, to_element

RAW = {"name": "Save", "control_type": 50000, "bounds": (10, 20, 110, 50), "automation_id": "saveBtn",
       "class_name": "Button", "enabled": True, "offscreen": False}


def raw(**changes):
    return {**RAW, **changes}


class TestToElement(unittest.TestCase):
    def test_button(self):
        el = to_element(RAW, hwnd=7)
        self.assertEqual(el["role"], "Button")
        self.assertEqual(el["action"], "click")
        self.assertEqual(el["bounds"], {"x": 10, "y": 20, "width": 100, "height": 30})
        self.assertEqual((el["hwnd"], el["automation_id"], el["source"]), (7, "saveBtn", "uia"))

    def test_edit_is_typed_into(self):
        el = to_element(raw(control_type=50004), hwnd=1)
        self.assertEqual((el["role"], el["action"]), ("TextInput", "type"))

    def test_offscreen_and_empty_are_skipped(self):
        self.assertIsNone(to_element(raw(offscreen=True), hwnd=1))
        self.assertIsNone(to_element(raw(bounds=(5, 5, 5, 40)), hwnd=1))

    def test_unnamed_containers_are_skipped(self):
        self.assertIsNone(to_element(raw(control_type=50033, name=""), hwnd=1))
        self.assertEqual(to_element(raw(control_type=50033, name="Sidebar"), hwnd=1)["role"], "Pane")

    def test_unknown_type_and_name_fallback(self):
        el = to_element(raw(control_type=99999, name="  "), hwnd=1)
        self.assertEqual((el["role"], el["name"]), ("Control", "saveBtn"))


def fake_element(name, control_type=50000, class_name="X"):
    rect = SimpleNamespace(left=0, top=0, right=50, bottom=20)
    return SimpleNamespace(CachedName=name, CachedControlType=control_type, CachedBoundingRectangle=rect,
                           CachedAutomationId="", CachedClassName=class_name, CachedIsEnabled=True,
                           CachedIsOffscreen=False)


def fake_found(elements):
    return SimpleNamespace(Length=len(elements), GetElement=lambda i: elements[i])


def fake_reader(root):
    reader = UiaReader()
    reader._unavailable = None
    reader._uia = MagicMock()
    reader._uia.ElementFromHandle.return_value = root
    reader._mod = SimpleNamespace(
        TreeScope_Descendants=4,
        TreeScope_Children=2,
        IUIAutomationInvokePattern=MagicMock(),
        IUIAutomationTogglePattern=MagicMock(),
        IUIAutomationSelectionItemPattern=MagicMock(),
        IUIAutomationValuePattern=MagicMock(),
        UIA_InvokePatternId=10000,
        UIA_TogglePatternId=10015,
        UIA_SelectionItemPatternId=10010,
        UIA_ValuePatternId=10002,
    )
    return reader


class TestUiaReader(unittest.TestCase):
    def test_reads_and_limits_elements(self):
        root = MagicMock(CurrentClassName="Notepad")
        root.FindAllBuildCache.return_value = fake_found([fake_element(f"b{i}") for i in range(5)])
        els = fake_reader(root).elements(1, max_elements=3)
        self.assertEqual([e["name"] for e in els], ["b0", "b1", "b2"])

    def test_chromium_window_is_warmed_up_once(self):
        root = MagicMock(CurrentClassName="Chrome_WidgetWin_1")
        root.FindAllBuildCache.return_value = fake_found([fake_element("Back")])
        reader = fake_reader(root)
        with patch.object(uia, "CHROMIUM_WARMUP_S", 0):
            reader.elements(5)
            reader.elements(5)
        scopes = [c.args[0] for c in root.FindAllBuildCache.call_args_list]
        self.assertEqual(scopes, [2, 4, 4])  # one warm-up read of the children, then full reads

    def test_unavailable_returns_none(self):
        reader = UiaReader()
        reader._unavailable = "not Windows"
        self.assertIsNone(reader.elements(1))

    def test_failure_returns_none(self):
        root = MagicMock(CurrentClassName="X")
        root.FindAllBuildCache.side_effect = OSError("COM error")
        self.assertIsNone(fake_reader(root).elements(1))

    def test_hung_app_times_out(self):
        reader = fake_reader(MagicMock())
        try:
            with patch.object(UiaReader, "_read", side_effect=lambda *a: time.sleep(2)):
                start = time.monotonic()
                self.assertIsNone(reader.elements(1, timeout=0.3))
            self.assertLess(time.monotonic() - start, 1.5)
        finally:
            reader.close()

    def test_missing_comtypes_disables_uia(self):
        reader = UiaReader()
        reader._unavailable = None
        with patch.dict(sys.modules, {"comtypes.client": None}):
            self.assertFalse(reader._ensure())
        self.assertFalse(reader.available)

    def test_ghost_invoke_success(self):
        reader = fake_reader(MagicMock())
        mock_el = MagicMock()
        mock_pat = MagicMock()
        mock_inv = MagicMock()
        mock_pat.QueryInterface.return_value = mock_inv
        mock_el.GetCurrentPattern.return_value = mock_pat
        reader._uia.ElementFromPoint.return_value = mock_el

        self.assertTrue(reader.invoke_at(50, 60))
        mock_inv.Invoke.assert_called_once()
        reader.close()

    def test_ghost_set_value_success(self):
        reader = fake_reader(MagicMock())
        mock_el = MagicMock()
        mock_pat = MagicMock()
        mock_val = MagicMock()
        mock_pat.QueryInterface.return_value = mock_val
        mock_el.GetCurrentPattern.return_value = mock_pat
        reader._uia.ElementFromPoint.return_value = mock_el

        self.assertTrue(reader.set_value_at(50, 60, "test text"))
        mock_val.SetValue.assert_called_once_with("test text")
        reader.close()

    def test_ghost_invoke_when_unavailable(self):
        reader = UiaReader()
        reader._unavailable = "not Windows"
        self.assertFalse(reader.invoke_at(10, 20))
        self.assertFalse(reader.set_value_at(10, 20, "val"))


@unittest.skipUnless(sys.platform == "win32", "ScreenPerceiver reads Win32 windows")
class TestPerceiverUsesUia(unittest.TestCase):
    def _perceiver(self, uia_result):
        from emiliano.cowork.perception import ScreenPerceiver

        reader = MagicMock()
        reader.elements.return_value = uia_result
        return ScreenPerceiver(uia_reader=reader)

    def _test_window(self):
        import ctypes

        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd and ctypes.windll.user32.IsWindow(hwnd):
            return hwnd
        return ctypes.windll.user32.GetDesktopWindow()

    def test_uia_elements_are_used(self):
        el = to_element(RAW, hwnd=1)
        els = self._perceiver([el]).get_ui_elements(self._test_window())
        self.assertEqual(els[0]["role"], "Window")
        self.assertEqual(els[1:], [el])

    def test_falls_back_to_win32_when_uia_finds_nothing(self):
        for result in (None, []):
            els = self._perceiver(result).get_ui_elements(self._test_window(), max_elements=10)
            self.assertEqual(els[0]["role"], "Window")
            self.assertTrue(all(e.get("source") != "uia" for e in els))


@unittest.skipUnless(sys.platform == "win32" and os.environ.get("EMILIANO_LIVE_UI_TESTS"),
                     "set EMILIANO_LIVE_UI_TESTS=1 on Windows to read the real taskbar")
class TestLiveTaskbar(unittest.TestCase):
    def test_taskbar_buttons_are_found(self):
        import ctypes

        hwnd = ctypes.windll.user32.FindWindowW("Shell_TrayWnd", None)
        els = UiaReader().elements(hwnd)
        self.assertTrue(els)
        self.assertIn("Button", {e["role"] for e in els})


if __name__ == "__main__":
    unittest.main()
