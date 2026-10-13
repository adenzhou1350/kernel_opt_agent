import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import knowledge_notes
from scout_lesson_context import MAX_CARD_BYTES, lesson_suggestions


class RoutedRowLessonTests(unittest.TestCase):
    def test_producer_identity_advice_is_scoped(self):
        result = lesson_suggestions('routed-row identity block-padded scatter_idx')
        card = result['matches'][0]
        self.assertEqual(card['id'], 'routed-row-identity-before-block-layout')
        knowledge_notes.validate(card)
        self.assertLessEqual(len(json.dumps(card, ensure_ascii=False).encode()), MAX_CARD_BYTES)
        self.assertIn('another producer', card['avoid_when'])
        self.assertIn('not a native kernel test', card['avoid_when'])

    def test_exact_humming_path_can_retrieve_counterexample(self):
        result = lesson_suggestions('Check alignment', source_urls=[
            'https://raw.githubusercontent.com/vllm-project/vllm/'
            'b9b401b2ef1db3148d480a1520d95c95eff9c528/'
            'vllm/model_executor/layers/fused_moe/experts/fused_humming_moe.py'])
        self.assertEqual(result['matches'][0]['id'], 'routed-row-identity-before-block-layout')
        self.assertEqual(result['matches'][0]['status'], 'counterexample')


if __name__ == '__main__':
    unittest.main()
