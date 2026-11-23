"""Regression coverage for detected key geometry and scoped teaching evidence."""

import io
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from backend.analysis.calibration import keyboard_mapping, pianocv_mapping
from backend.analysis.fingering_match import fingertip_scores, keyboard_regions
from backend.analysis.technique_graph import analyze_exercise, exercise_catalog, graph_index, segment_evidence
from backend.services.coach import create_message, make_evidence


class TechniqueGraphTests(unittest.TestCase):
    def test_detected_key_faces_are_used_and_mirrored_pitches_are_ordered(self):
        corners = [[50, 50], [1090, 50], [1090, 150], [50, 150]]
        for mirrored in (False, True):
            template = keyboard_mapping(corners, 1140, 200, 21, 108, mirrored)
            keys = []
            for key in template["key_centers"]:
                x, y = key["x"], key["y"]
                face = [[x - 3, y - 4], [x + 3, y - 4], [x + 3, y + 4], [x - 3, y + 4]]
                keys.append(dict(midi_pitch=key["midi_pitch"], outline=face, surface=face))
            mapping = pianocv_mapping("pianocv_crop", corners, keys, 1140, 200, mirrored)
            positions = {key["midi_pitch"]: key for key in mapping["key_centers"]}
            transform, regions = keyboard_regions(mapping, positions)
            np.testing.assert_array_equal(regions[65].outline, np.rint(keys[44]["outline"]))
            point = {"x": positions[65]["x"], "y": positions[65]["y"]}
            row = dict(start_frame=1, sample_frames=[0, 1, 2],
                       hands_by_frame={str(i): {"right": [point] * 21} for i in range(3)})
            score = fingertip_scores(row, regions[65], positions[65], transform)
            self.assertGreater(score["right", 1][0], .95)
            with self.assertRaises(ValueError):
                pianocv_mapping("pianocv_auto", corners, keys[:-1], 1140, 200, mirrored)
            with self.assertRaises(ValueError):
                pianocv_mapping("pianocv_auto", corners, keys, 1140, 200, not mirrored)

    def test_calculates_timing_and_motion_only_when_supported(self):
        rows = self.attempt_notes()
        track = io.StringIO()
        for frame in range(110):
            x = 23 - min(3, max(0, frame - 61) * .46)
            points = [{"x": x - 2, "y": 2}, {"x": x - 1, "y": 1}, {"x": x, "y": 1}]
            track.write(json.dumps([["right", [{}, {}] + points + [{}] * 16]]) + "\n")
        regions = {65: SimpleNamespace(center=20)}
        report = analyze_exercise(rows, track, np.eye(3), regions, 40, .5)
        attempt, = report["attempts"]
        self.assertEqual((attempt["start"], attempt["end"]), (1.4, 1.7))
        self.assertEqual(attempt["ratio"], 1.5)
        self.assertEqual(attempt["score_note_ids"], ["T02_N03", "T02_N04"])
        self.assertEqual(attempt["motion"]["status"], "observed")
        self.assertEqual(attempt["motion"]["preparation_estimate_ms"], 175)
        self.assertEqual(attempt["motion"]["joint_angle_2d_deg"], 135)
        self.assertEqual(attempt["motion"]["distance_white_keys"], 0)

        absent_hands = io.StringIO("[]\n" * 110)
        result = analyze_exercise(rows, absent_hands, np.eye(3), regions, 40, .5)["attempts"][0]
        self.assertEqual(result["motion"]["status"], "insufficient_landmarks")
        self.assertEqual(result["ratio"], 1.5)
        rows[3]["hand"] = "left"
        result = analyze_exercise(rows, track, np.eye(3), regions, 40, .5)["attempts"][0]
        self.assertEqual(result["motion"]["status"], "fingering_unconfirmed")
        rows[2]["pitch"] = 63
        self.assertEqual(analyze_exercise(rows, track, np.eye(3), regions, 40, .5)["attempts"], [])

    def test_coach_receives_same_segment_and_graph_references(self):
        rows = self.attempt_notes()
        report = analyze_exercise(rows, io.StringIO("[]\n" * 110), np.eye(3), {65: SimpleNamespace(center=20)}, 40, .5)
        summary = dict(video_duration_seconds=3, offset_seconds=.5, technique=report)
        artifacts = SimpleNamespace(read_json=lambda _: summary, note_rows=lambda _: rows)
        folder = Path(".")
        self.assertNotIn("technique", make_evidence(artifacts, folder, 1.1, 1.6, []))
        self.assertNotIn("technique", make_evidence(artifacts, folder, 1.1, 1.9, ["2"]))
        data = dict(question="这个换指该怎么练？", start=1.1, end=1.9, note_ids=["2", "3"], send=True)
        with patch("backend.services.coach.ask_model", return_value="来自测试模型的答复") as model:
            message = create_message(data, folder, {"model": "test"}, artifacts)
        _, evidence, references, _ = model.call_args.args
        self.assertEqual([note["id"] for note in evidence["notes"]], ["2", "3"])
        self.assertEqual({rule["id"] for rule in evidence["technique"]["rules"]}, {"R02", "R03", "R08"})
        self.assertFalse(evidence["technique"]["thresholds_validated"])
        self.assertTrue({"P07", "P08", "S05"} <= {ref["id"] for ref in references})
        self.assertNotIn("P02", {ref["id"] for ref in references})
        self.assertEqual(message["status"], "answered")

    def test_descending_scale_uses_middle_finger_and_retrieves_its_own_sources(self):
        rows = self.attempt_notes((72, 71, 69, 67, 65, 64, 62, 60), (5, 4, 3, 2, 1, 3, 2, 1))
        track = io.StringIO()
        for frame in range(110):
            middle = [{"x": 18, "y": 2}, {"x": 19, "y": 1}, {"x": 20, "y": 1}]
            track.write(json.dumps([["right", [{}] * 10 + middle + [{}] * 8]]) + "\n")
        report = analyze_exercise(rows, track, np.eye(3), {64: SimpleNamespace(center=20)}, 40, .5, "T03")
        attempt, = report["attempts"]
        self.assertEqual(attempt["note_names"], ["F4", "E4"])
        self.assertEqual(attempt["expected_fingers"], [1, 3])
        self.assertEqual(attempt["motion"]["joint_angle_2d_deg"], 135)
        self.assertEqual(attempt["motion"]["fingertip_px"], [20, 1])
        evidence, sources = segment_evidence(report, 1.6, 2.2, [])
        self.assertEqual({rule["id"] for rule in evidence["rules"]}, {"R02", "R03", "R08", "R09"})
        self.assertIn("P03", {source["id"] for source in sources})
        self.assertNotIn("P02", {source["id"] for source in sources})

    def test_g_major_requires_f_sharp_and_keeps_repeatability_within_selection(self):
        pitches, fingers = (67, 69, 71, 72, 74, 76, 78, 79), (1, 2, 3, 1, 2, 3, 4, 5)
        rows = self.attempt_notes(pitches, fingers)
        second = self.attempt_notes(pitches, fingers)
        for index, row in enumerate(second, 8):
            row.update(note_index=str(index), start_seconds=row["start_seconds"] + 2.5)
        report = analyze_exercise(rows + second, io.StringIO("[]\n" * 220), np.eye(3),
                                  {72: SimpleNamespace(center=20)}, 40, .5, "T04")
        self.assertEqual(report["repeatability"]["count"], 2)
        self.assertEqual(report["repeatability"]["ratio_mad"], 0)
        self.assertEqual(report["attempts"][0]["note_names"], ["B4", "C5"])
        full, _ = segment_evidence(report, 1, 5, [])
        self.assertIn("R07", {rule["id"] for rule in full["rules"]})
        partial, _ = segment_evidence(report, 1, 2, [])
        self.assertIsNone(partial["repeatability"])
        self.assertNotIn("R07", {rule["id"] for rule in partial["rules"]})
        rows[6]["pitch"] = 77
        changed = analyze_exercise(rows, io.StringIO(), np.eye(3), {}, 40, .5, "T04")
        self.assertFalse(changed["attempts"])

    def test_catalog_connects_all_active_rules_to_metrics_and_reviewed_sources(self):
        catalog = exercise_catalog()
        self.assertEqual([exercise["id"] for exercise in catalog["exercises"]], ["T02", "T03", "T04"])
        _, nodes, edges = graph_index()
        for (source, _), targets in edges.items():
            self.assertIn(source, nodes)
            for target in targets:
                self.assertIn(target, nodes)
        for exercise in catalog["exercises"]:
            self.assertEqual(len(exercise["note_names"]), 8)
            self.assertEqual(len(exercise["rules"]), 5)
            sources = {source["id"] for source in exercise["references"]}
            for rule in exercise["rules"]:
                self.assertTrue(rule["advice"] and rule["metrics"] and rule["reference_ids"])
                self.assertLessEqual(set(rule["reference_ids"]), sources)

    @staticmethod
    def attempt_notes(pitches=(60, 62, 64, 65, 67, 69, 71, 72), fingers=(1, 2, 3, 1, 2, 3, 4, 5)):
        onsets = (.5, .7, .9, 1.2, 1.4, 1.6, 1.8, 2)
        return [dict(note_index=str(index), pitch=pitch, note_name=str(pitch), start_seconds=time, start_frame=20,
                     status="matched", hand="right", finger=finger)
                for index, (pitch, time, finger) in enumerate(zip(pitches, onsets, fingers))]
