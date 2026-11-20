import unittest
from unittest.mock import patch

from backend.analysis.calibration import keyboard_mapping
from backend.analysis.fingering_match import assign_fingers, keyboard_regions, transform_points


class FingeringMatchTests(unittest.TestCase):
    def setUp(self):
        self.corners = [[20, 100], [540, 100], [540, 300], [20, 300]]

    def keyboard(self, mirrored=False):
        mapping = keyboard_mapping(self.corners, 560, 320, 21, 108, mirrored)
        keys = {key["midi_pitch"]: key for key in mapping["key_centers"]}
        transform, regions = keyboard_regions(mapping, keys)
        return keys, transform, regions

    def test_accepts_finger_at_front_of_white_key_with_either_orientation(self):
        for mirrored in (False, True):
            with self.subTest(mirrored=mirrored):
                keys, transform, regions = self.keyboard(mirrored)
                x = keys[60]["x"]
                hand = [{"x": 10, "y": 310}] * 21
                hand[8] = {"x": x, "y": 294}
                row = {"start_frame": 12, "start_seconds": .4, "pitch": 60, "sample_frames": [11, 12, 13],
                       "hands_by_frame": {str(frame): {"right": hand} for frame in (11, 12, 13)}}
                result, = assign_fingers([row], keys, regions, transform)
                self.assertEqual(result[:3], ("matched", "", ("right", 2)))

    def test_white_region_excludes_the_neighboring_black_key_at_the_back(self):
        keys, transform, regions = self.keyboard()
        pitch = 60
        x_black = keys[61]["x"]
        black_x, _ = transform_points([(x_black, 150)], transform)[0]
        black_hand = [{"x": 10, "y": 310}] * 21
        black_hand[8] = {"x": x_black + .10, "y": 150}
        white_hand = [{"x": 10, "y": 310}] * 21
        white_hand[8] = {"x": keys[pitch]["x"], "y": 150}
        self.assertGreater(black_x, regions[pitch].center)
        row = {"start_frame": 12, "start_seconds": .4, "pitch": pitch, "sample_frames": [11, 12, 13],
               "hands_by_frame": {str(frame): {"left": black_hand, "right": white_hand} for frame in (11, 12, 13)}}
        result, = assign_fingers([row], keys, regions, transform)
        self.assertEqual(result[:3], ("matched", "", ("right", 2)))

    def test_assigns_chord_together_and_preserves_no_hand_and_outside_video(self):
        keys, transform, regions = self.keyboard()
        rows = [{"start_frame": 12, "start_seconds": .40, "pitch": 60},
                {"start_frame": 13, "start_seconds": .42, "pitch": 64},
                {"start_frame": 30, "start_seconds": 1.0, "pitch": 60},
                {"start_frame": None, "start_seconds": 2, "pitch": 60}]
        with patch("backend.analysis.fingering_match.fingertip_scores", side_effect=[
            {("right", 1): (.93, 3, 0), ("right", 2): (.75, 3, 0)},
            {("right", 1): (.90, 3, 0)},
            {},
        ]):
            results = assign_fingers(rows, keys, regions, transform)
        self.assertEqual([row[:3] for row in results], [
            ("matched", "", ("right", 2)),
            ("matched", "", ("right", 1)),
            ("unmatched", "no_hand", None),
            ("unmatched", "outside_video", None),
        ])
