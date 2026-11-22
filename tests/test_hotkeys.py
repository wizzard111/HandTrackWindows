import sys

import pytest

from handtrack import hotkeys


def test_parse_and_display():
    assert hotkeys.parse("ctrl+alt+h") == (frozenset({"ctrl", "alt"}), "h")
    assert hotkeys.parse("Shift + Command + F5") == (frozenset({"shift", "win"}), "f5")
    assert hotkeys.display_text("alt+ctrl+h") == "Ctrl + Alt + H"
    assert hotkeys.display_text("ctrl+shift+pagedown") == "Ctrl + Shift + Pagedown"
    assert hotkeys.display_text(hotkeys.DEFAULT_HIDE_FACE) == "Ctrl + Alt + H"


@pytest.mark.parametrize("bad", ["h", "ctrl+alt", "ctrl+h+j", "ctrl+banana", "", "ctrl+f25"])
def test_rejects_bad_bindings(bad):
    with pytest.raises(ValueError):
        hotkeys.parse(bad)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows RegisterHotKey")
def test_windows_registers_and_reports_a_taken_combination():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    first, second = hotkeys.GlobalHotkey(), hotkeys.GlobalHotkey()
    combo = "ctrl+alt+shift+f19"                  # nobody uses this one
    try:
        assert first.set_binding(combo) is None
        err = second.set_binding(combo)
        assert err and "already used" in err
        first.stop()
        assert second.set_binding(combo) is None   # free again once released
    finally:
        first.stop()
        second.stop()


def test_key_recorder_finishes_once_and_goes_inert():
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QLineEdit

    from handtrack.ui.main_window import KeyRecorder
    QApplication.instance() or QApplication([])
    field = QLineEdit()
    rec = KeyRecorder(field, "combo")
    got = []
    rec.finished.connect(got.append)
    QTest.keyPress(field, Qt.Key.Key_Control)
    QTest.keyPress(field, Qt.Key.Key_Shift)
    QTest.keyPress(field, Qt.Key.Key_K)
    QTest.keyRelease(field, Qt.Key.Key_K)
    assert got == ["ctrl+shift+k"]
    # Deletion may still be pending: further keys must neither be swallowed nor recorded.
    QTest.keyPress(field, Qt.Key.Key_A)
    QTest.keyRelease(field, Qt.Key.Key_A)
    assert got == ["ctrl+shift+k"]
    assert field.text() == "a"
