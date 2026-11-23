import unittest

from backend.analysis.score_revisions import change_review, effective_report


class ScoreRevisionsTests(unittest.TestCase):
    def test_reassigns_a_note_without_changing_original_candidates_or_claiming_it_twice(self):
        score = dict(id="r1", score_note_id="r1", time=1.1, expected_time=1.1,
                     performance_id="1", expected_note="C4", played_note="D4", status="pitch_candidate")
        extra = dict(id="p:2", score_note_id=None, time=1.2, performance_id="2",
                     played_note="C4", status="extra_candidate")
        report = dict(status="aligned", rows=[score, extra])
        predictions = [dict(note_index=identifier, note_name=name, start_seconds=time,
                            start_frame=30, status="matched", finger=finger, hand="right")
                       for identifier, name, time, finger in [("1", "D4", 1.1, 2), ("2", "C4", 1.2, 3)]]
        changed = change_review(report, predictions, 0, dict(row_id="r1", performance_id="2", fingers=[1, 2]))
        effective = effective_report(changed, predictions, 0)
        fixed = next(row for row in effective["rows"] if row["id"] == "r1")
        self.assertEqual((fixed["status"], fixed["performance_id"]), ("matched_pitch", "2"))
        self.assertTrue(fixed["fingering_difference"])
        self.assertEqual(fixed["reference_finger_source"], "manual")
        self.assertEqual({row["id"] for row in effective["rows"]}, {"r1", "p:1"})
        self.assertEqual(report["rows"][0]["played_note"], "D4")
        restored = change_review(changed, predictions, 0, dict(row_id="r1", restore_pairing=True))
        effective = effective_report(restored, predictions, 0)
        self.assertEqual(effective["rows"][0]["status"], "pitch_candidate")
        self.assertEqual(effective["rows"][0]["reference_fingers"], [1, 2])
        self.assertEqual(effective["rows"][1]["id"], "p:2")
        other = dict(score, id="r2", score_note_id="r2", performance_id="2", played_note="C4")
        with self.assertRaisesRegex(ValueError, "已对应另一谱音"):
            change_review(dict(report, rows=[score, other]), predictions, 0, dict(row_id="r1", performance_id="2"))
        unclear = change_review(report, predictions, 0, dict(row_id="r1", verdict="unclear"))
        effective = effective_report(unclear, predictions, 0)
        self.assertEqual(effective["rows"][0]["manual_review"], "unclear")
        self.assertEqual(effective["rows"][0]["status"], "review")
