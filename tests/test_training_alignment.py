import base64
import unittest

from training_sites import alignment, demo
from training_sites.server import align_api, score_api


class AlignmentTrainingTests(unittest.TestCase):
    def test_validation_labels_do_not_choose_model(self):
        dataset = demo.alignment_dataset()
        trained = alignment.train(dataset)
        validation = set(trained['validation_pieces'])
        self.assertTrue(validation)
        self.assertFalse(validation.intersection(trained['training_pieces']))
        self.assertEqual(len(trained['trials']), 18)
        self.assertGreater(trained['validation']['adaptive']['f1'], trained['validation']['fixed']['f1'])
        self.assertEqual(alignment.read_model(trained['model']).chord_window_ms, 75)

        for sample in dataset['examples']:
            if sample['piece_id'] in validation:
                sample['matches'] = sample['matches'][:1]
        rescored = alignment.train(dataset)
        self.assertEqual(trained['model'], rescored['model'])
        self.assertEqual(trained['trials'], rescored['trials'])
        self.assertNotEqual(trained['validation'], rescored['validation'])

    def test_rejects_a_duplicate_alignment_label(self):
        dataset = demo.alignment_dataset()
        matches = dataset['examples'][0]['matches']
        matches.append(matches[0])
        with self.assertRaisesRegex(ValueError, '互不重复'):
            alignment.read_dataset(dataset)

    def test_exported_excerpt_is_accepted_as_alignment_input(self):
        xml = {'name': 'demo.musicxml', 'data': base64.b64encode(demo.score_file()).decode()}
        self.assertEqual(len(score_api({'file': xml})['measures']), 8)
        excerpt = score_api({'file': xml, 'first': 2, 'last': 5}, export=True)
        self.assertEqual(excerpt['tracks'], 2)
        self.assertEqual(len(excerpt['tempos']), 2)
        midi = {'name': 'excerpt.mid', 'data': excerpt['midi']}
        result = align_api({'reference': midi, 'performance': midi,
                            'model': alignment.model_document(alignment.DEFAULT)})
        self.assertEqual(len(result['adaptive']['pairs']), len(excerpt['notes']))
