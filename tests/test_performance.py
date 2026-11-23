"""Verify that reference assumptions never become invented audio measurements."""

import unittest

from backend.analysis.performance import align_reference
from backend.analysis.performance_graph import build_graph, graph_segment
from backend.analysis.symbolic_alignment import Note


class PerformanceTests(unittest.TestCase):
    def test_audio_timing_and_score_projection_remain_distinct(self):
        reference = [Note(str(i), 60 + i % 7, i * .5, .3) for i in range(40)]
        played = [Note(str(i), row.pitch, row.onset * 1.2 + .7, .25) for i, row in enumerate(reference)]
        events, anchors = align_reference(reference, played, 26)
        self.assertGreater(len(anchors), 3)
        self.assertEqual(sum(row['timing_source'] == 'audio' for row in events), 40)
        empty, _ = align_reference(reference, [], 26)
        self.assertTrue(all(row['timing_delta_ms'] is None for row in empty))
        self.assertTrue(all(row['timing_source'] == 'score_projection' for row in empty))

    def test_long_recordings_and_selected_graph_scope(self):
        reference = [Note(str(i), 48 + i % 30, i * .3, .2) for i in range(1300)]
        played = [Note(str(i), row.pitch, row.onset + .2, .2) for i, row in enumerate(reference)]
        timings, _ = align_reference(reference, played, 400)
        passage = dict(title='test', notes=[dict(id=row.id, pitch=row.pitch, name=str(row.pitch),
            onset=row.onset, duration=row.duration, reference_fingers=[]) for row in reference])
        predictions = [dict(note_index=str(i), finger='1', hand='right', confidence='.8') for i in range(1300)]
        graph, report = build_graph(passage, predictions, timings, {'key_centers':[]}, 400)
        self.assertEqual(graph['summary']['notes'], 1300)
        self.assertEqual(len(report['rows']), 1300)
        selected = graph_segment(graph, 0, 400, ['1299'])
        self.assertEqual(selected['summary']['notes'], 1)
        self.assertEqual(selected['events'][0]['id'], '1299')
        self.assertTrue(all(row['status'] == 'score_linked' for row in report['rows']))


if __name__ == '__main__':
    unittest.main()
