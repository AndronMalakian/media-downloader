import functools
import http.server
import tempfile
import threading
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from downloader import MediaDownloader


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


class LocalDownloadTests(unittest.TestCase):
    def test_real_ytdlp_downloads_file_and_reports_completion(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "sample.wav"
            with wave.open(str(source), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(8000)
                audio.writeframes(b"\0\0" * 8000)
            handler = functools.partial(QuietHandler, directory=folder)
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            events = []
            try:
                dl = MediaDownloader(events.append)
                with patch("downloader.ensure_pot_server"), patch("downloader.build_runtime_opts", return_value={"proxy": ""}):
                    dl.download(
                        f"http://127.0.0.1:{server.server_port}/sample.wav",
                        root / "downloads", mode="custom", custom_format="best", custom_audio_only=True,
                    )
                self.assertEqual(dl.progress.status, "done", dl.progress.error)
                files = list((root / "downloads").glob("*.wav"))
                self.assertEqual(len(files), 1)
                self.assertEqual(files[0].read_bytes(), source.read_bytes())
                self.assertIn("downloading", [event.status for event in events])
                self.assertEqual(events[-1].status, "done")
            finally:
                server.shutdown()
                server.server_close()
                worker.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
