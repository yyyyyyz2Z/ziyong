import base64
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from training_sites import demo
from training_sites.server import recognize_api, score_api


class ScoreRecognitionTests(unittest.TestCase):
    def test_recognized_score_can_export_without_running_recognition_again(self):
        pdf = {"name": "my piano score.pdf", "data": base64.b64encode(b"%PDF-1.7\n").decode()}

        def fake_run(command, **kwargs):
            self.assertEqual(command[1:5], ["-batch", "-transcribe", "-export", "-output"])
            self.assertEqual(Path(command[-1]).name, "score.pdf")
            self.assertTrue(Path(command[-1]).read_bytes().startswith(b"%PDF-"))
            (Path(command[5]) / "score.musicxml").write_bytes(demo.score_file())
            return SimpleNamespace(returncode=0)

        with patch("training_sites.recognition.subprocess.run", side_effect=fake_run) as runner:
            recognized = recognize_api({"file": pdf}, Path("Audiveris.exe"))
            self.assertEqual(len(score_api(recognized)["measures"]), 8)
            excerpt = score_api({**recognized, "first": 2, "last": 3}, export=True)
            self.assertEqual(len(excerpt["notes"]), 12)
            runner.assert_called_once()

    def test_pdf_error_reports_missing_engine(self):
        pdf = {"name": "score.pdf", "data": base64.b64encode(b"%PDF-1.7\n").decode()}
        with self.assertRaisesRegex(ValueError, "找不到 Audiveris"):
            recognize_api({"file": pdf}, None)
