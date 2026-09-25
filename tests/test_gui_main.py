"""The main window still stands up with the interpretation wiring in it."""

from revolv.gui import FileRow, Job, MainWindow, SettingsPanel


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
