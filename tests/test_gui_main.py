"""The main window still stands up with the interpretation wiring in it."""

from revolv.gui import (FileRow, Job, MainWindow, SettingsPanel,
                        diarize_without_token)


def test_diarize_without_token_guard():
    """The silent-UNKNOWN trap (dogfood 2026-09-25): warn exactly when
    speaker labels are requested but no token exists to power them."""
    assert diarize_without_token({"diarize": True, "hf_token": ""})
    assert diarize_without_token({"diarize": True, "hf_token": "  "})
    assert not diarize_without_token({"diarize": True, "hf_token": "hf_x"})
    assert not diarize_without_token({"diarize": False, "hf_token": ""})


def test_main_window_and_settings_panel_construct(qapp):
    window = MainWindow()
    try:
        panel = SettingsPanel(window)
        # The Interpretation group exists with the new controls.
        assert panel.interpret_check.isChecked() in (True, False)
        assert panel.provider_box.count() == 2
        assert panel.retention_box.count() == 3
        assert panel.base_url_edit.text().startswith("http")
        panel._applied = True  # keep hideEvent from saving user settings
        panel.deleteLater()
    finally:
        window.deleteLater()


def test_settings_panel_adds_v1_to_a_bare_base_url(qapp, tmp_path,
                                                    monkeypatch):
    """Fix list #11: what the popover saves is what the provider will call."""
    window = MainWindow()
    try:
        # Keep the test's settings out of the real settings file.
        window.settings.path = tmp_path / "settings.json"
        logged = []
        monkeypatch.setattr(window, "log", logged.append)
        monkeypatch.setattr(window, "detect_hardware", lambda: None)
        panel = SettingsPanel(window)
        panel.base_url_edit.setText("http://127.0.0.1:1234")
        panel.apply()
        assert window.settings["provider_base_url"] == "http://127.0.0.1:1234/v1"
        assert any("/v1" in line for line in logged)

        panel.base_url_edit.setText("http://127.0.0.1:1234/v1")
        logged.clear()
        panel.apply()
        assert window.settings["provider_base_url"] == "http://127.0.0.1:1234/v1"
        assert not any("/v1" in line for line in logged)
        panel._applied = True
        panel.deleteLater()
    finally:
        window.deleteLater()


def test_file_row_actions_show_only_when_done(qapp):
    job = Job("call.mp4")
    row = FileRow(job)
    row.set_actions(lambda: None, lambda: None, lambda: None)
    assert not row.context_button.isVisibleTo(row.parentWidget() or row)
    row.set_state("done", "done")
    assert row.context_button.isVisibleTo(row)
    assert row.results_button.isVisibleTo(row)
    assert row.interpret_button.isVisibleTo(row)
    row.set_state("active", "again", 0.5)
    assert not row.context_button.isVisibleTo(row)
    row.deleteLater()
