import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from music21 import bar, key, meter, note, stream, tempo, tie

from backend.analysis.score_excerpt import export_excerpt
from backend.analysis.score_loader import load_score


class ScoreExcerptTests(unittest.TestCase):
    def test_extracts_both_hands_with_tempos_ties_and_written_measure_order(self):
        score = stream.Score()
        right = stream.Part()
        left = stream.Part()
        score.insert(0, right)
        score.insert(0, left)

        opening = note.Note('C4', quarterLength=2)
        opening.tie = tie.Tie('start')
        carried = note.Note('C4', quarterLength=1)
        carried.tie = tie.Tie('stop')
        sustained = note.Note('E4', quarterLength=2)
        sustained.tie = tie.Tie('start')
        tail = note.Note('E4', quarterLength=1)
        tail.tie = tie.Tie('stop')
        right_notes = ((opening,), (carried, note.Note('D4')), (sustained,), (tail, note.Note('F4')))
        left_notes = (
            (note.Note('C3', quarterLength=2),),
            (note.Note('G3', quarterLength=2),),
            (note.Rest(), note.Note('B3')),
            (note.Note('A3', quarterLength=2),),
        )
        for part, measures in ((right, right_notes), (left, left_notes)):
            for number, notes in enumerate(measures, 1):
                measure = stream.Measure(number=number)
                if number == 1:
                    measure.insert(0, meter.TimeSignature('2/4'))
                    measure.insert(0, key.KeySignature(1))
                    if part is right:
                        measure.insert(0, tempo.MetronomeMark(number=60))
                    measure.leftBarline = bar.Repeat(direction='start')
                if number == 2:
                    measure.rightBarline = bar.Repeat(direction='end')
                if number == 3 and part is right:
                    measure.insert(0, tempo.MetronomeMark(number=120))
                for event in notes:
                    measure.append(event)
                part.append(measure)

        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = Path(score.write('musicxml', fp=root / 'score.musicxml'))
            notes = load_score(export_excerpt(source, root / 'excerpt.mid', 2, 3))

        events = [(row['pitch'], round(row['start_seconds'], 3), round(row['end_seconds'], 3))
                  for row in notes]
        self.assertEqual(events, [(55, 0, 2), (60, 0, 1), (62, 1, 2), (64, 2, 3), (59, 2.5, 3)])
