import tempfile
import threading
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

import main
from downloader import DownloadProgress


class UITests(unittest.TestCase):
    """Реальное окно Tk, без сети, загрузок и пользовательского конфига."""

    @classmethod
    def setUpClass(cls):
        try:
            probe = tk.Tk()
            probe.update_idletasks()
            probe.destroy()
        except tk.TclError as error:
            raise unittest.SkipTest(f"Tk display unavailable: {error}")
        cls.temp = tempfile.TemporaryDirectory()
        cls.patches = [
            patch.object(main, "CONFIG_FILE", Path(cls.temp.name) / "config.json"),
            patch.object(main, "LEGACY_CONFIG_FILE", Path(cls.temp.name) / "legacy.json"),
            patch.object(main, "detect_browsers", return_value=[]),
            patch.object(main.YTApp, "_check_updates_async"),
            patch.object(main.YTApp, "_autostart_pot"),
            patch.object(main.YTApp, "_check_components"),
            patch.object(main.YTApp, "_check_ffmpeg"),
        ]
        for context in cls.patches:
            context.start()
        cls.app = main.YTApp()
        cls.app.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.app._closing = True
        cls.app.destroy()
        for context in reversed(cls.patches):
            context.stop()
        cls.temp.cleanup()

    def setUp(self):
        self.app._q_running = False
        self.app.playlist_all_var.set(True)
        self.app.url_var.set("")
        self.app._queue_clear()

    def test_all_playlist_ignores_old_range(self):
        self.app.playlist_start_var.set(8)
        self.app.playlist_end_var.set(2)
        self.assertEqual(self.app._playlist_range(), (1, 0))

    def test_malformed_playlist_range_is_rejected(self):
        self.app.playlist_all_var.set(False)
        self.app.playlist_start_var.set("invalid")
        with self.assertRaises(ValueError):
            self.app._playlist_range()
        self.app.playlist_start_var.set(1)

    def test_queue_rejects_invalid_and_duplicate_links(self):
        self.assertFalse(self.app._queue_append("not a link"))
        self.assertTrue(self.app._queue_append("https://example.com/video"))
        self.assertFalse(self.app._queue_append("https://example.com/video"))
        self.assertEqual(len(self.app.queue_items), 1)

    def test_late_progress_does_not_overwrite_final_status(self):
        self.app._queue_append("https://example.com/video")
        item = self.app.queue_items[0]
        item.update(status="готово", percent=100)
        progress = DownloadProgress()
        progress.status = "downloading"
        progress.percent = 20
        self.app._queue_on_progress(item, progress)
        self.assertEqual((item["status"], item["percent"]), ("готово", 100))

    def test_changing_url_clears_selected_format(self):
        self.app._selected_format = "137+140"
        self.app.url_var.set("https://example.com/new")
        self.assertIsNone(self.app._selected_format)

    def test_stale_info_is_not_shown_for_another_url(self):
        self.app.url_var.set("https://example.com/new")
        self.app._present_info("https://example.com/old", {"title": "Old title"})
        self.assertNotIn("Old title", self.app.title_lbl.cget("text"))

    def test_worker_can_post_without_calling_tk(self):
        result = []
        thread = threading.Thread(target=lambda: self.app._post_ui(lambda: result.append("done")))
        thread.start()
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result, [])
        self.app._drain_ui_events()
        self.assertEqual(result, ["done"])

    def test_controls_fit_small_window(self):
        self.app.deiconify()
        self.app.minsize(900, 620)
        self.app.geometry("900x700")
        self.app.update()
        for widget in (self.app.btn_download, self.app.btn_stop, self.app.progress_bar):
            bottom = widget.winfo_rooty() + widget.winfo_height()
            self.assertLessEqual(bottom, self.app.winfo_rooty() + self.app.winfo_height())
        self.assertGreater(self.app.nb.winfo_height(), 100)
        self.app.withdraw()


if __name__ == "__main__":
    unittest.main()
