import tempfile
import unittest
from pathlib import Path

from backend.analysis.score_review import analyze_passage, score_document, score_guidance, score_segment, select_passage


class ScoreReviewTests(unittest.TestCase):
    def test_preserves_score_coordinates_across_parts_and_selected_bars(self):
        from music21 import articulations, chord, meter, note, stream, tempo

        score = stream.Score()
        for pitches in [("C4", "E4", "G4"), ("C3", "E3", "G3")]:
            part = stream.Part()
            for number in (1, 2):
                measure = stream.Measure(number=number)
                if number == 1:
                    measure.insert(0, meter.TimeSignature("6/8"))
                    measure.insert(0, tempo.MetronomeMark(number=120))
                    measure.insert(0, note.Rest(quarterLength=3))
                else:
                    tone = note.Note(pitches[0], quarterLength=.5)
                    tone.articulations.append(articulations.Fingering(1))
                    measure.insert(.5, tone)
                    measure.insert(1.5, chord.Chord(pitches[1:], quarterLength=1.5))
                part.append(measure)
            score.insert(0, part)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "fixture.musicxml"
            score.write("musicxml", fp=str(source))
            document = score_document(source)
        selected = select_passage(document, 2, 2)
        self.assertEqual(len(selected["notes"]), 6)
        first = selected["notes"][0]
        self.assertEqual(first["measure_label"], "2")
        self.assertAlmostEqual(first["beat"], 1 + 1 / 3)
        self.assertAlmostEqual(first["onset"], .25)
        self.assertEqual(first["reference_fingers"], [1])
        self.assertEqual({row["part"] for row in selected["notes"]}, {1, 2})
        with self.assertRaises(ValueError):
            select_passage(document, 2, 1)

    def test_reuses_warping_and_limits_error_candidates_to_selected_evidence(self):
        pitches = [60, 62, 64, 65, 67, 69, 71, 72, 74, 76]
        notes, played = [], []
        for index, pitch in enumerate(pitches):
            onset = index * .5
            bar = index // 5 + 1
            notes.append(dict(id=f"r{index}", pitch=pitch, name=str(pitch), measure=bar, measure_label=str(bar),
                              beat=index % 5 + 1, score_beat=index, onset=onset, duration=.2,
                              part=1, voice=None, reference_fingers=[1] if index == 1 else []))
            if index == 6:
                continue
            if index == 4:
                pitch = 68
            actual = 2 + index * .4 + .015 * max(0, index - 4) ** 2
            played.append(dict(note_index=str(index), pitch=pitch, start_seconds=actual, end_seconds=actual + .2,
                               start_frame=30, note_name=str(pitch), status="matched", finger=2, hand="right"))
        passage = dict(title="fixture", first=1, last=2, measures=[dict(position=i, label=str(i)) for i in (1, 2)],
                       notes=notes, ornament_measures=[])
        result = analyze_passage(passage, played, .25)
        self.assertEqual(result["status"], "aligned")
        self.assertEqual(result["counts"], dict(matched_pitch=8, pitch_candidate=1, missing_candidate=1))
        self.assertAlmostEqual(next(row["time"] for row in result["rows"] if row["id"] == "r1"), 2.65)
        selected = score_segment(result, 2.5, 5.5, ["1"])
        self.assertEqual(selected["total"], 1)
        self.assertTrue(selected["rows"][0]["fingering_difference"])
        rules, references = score_guidance(selected)
        self.assertEqual({rule["id"] for rule in rules}, {"R01", "R10", "R11"})
        self.assertTrue({"P08", "P13"} <= {source["id"] for source in references})

        # Give the unpaired note a second voice on the very same physical key.
        # Its isolated missing-attack hypothesis must become uncertain.
        repeated = dict(notes[6], id="duplicate", part=2)
        references = sorted(notes + [repeated], key=lambda row: row["score_beat"])
        duplicate = analyze_passage(dict(passage, notes=references), played, .25)
        self.assertNotIn("missing_candidate", duplicate["counts"])
        unrelated = [dict(row, pitch=row["pitch"] - 24) for row in played]
        refused = analyze_passage(passage, unrelated, .25)
        self.assertEqual(refused["status"], "insufficient")
        self.assertFalse(refused["rows"])
