"""Pure comparison regression; runnable without database or ML dependencies."""
import ast
import math
import unittest
from pathlib import Path

source = Path(__file__).parents[1] / 'app' / 'forecasting' / 'patterns.py'
tree = ast.parse(source.read_text(encoding='utf-8-sig'))
names = {'_mean', '_pearson', '_driver'}
namespace = {'math': math, 'MIN_NIGHTS': 10, 'MIN_EFFECT': 15.0}
exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names], type_ignores=[]), str(source), 'exec'), namespace)

class PatternCopyTests(unittest.TestCase):
    def test_comparison_is_actual_averages_not_mislabelled_percent(self):
        pairs = [(i, 10 if i < 10 else 15 if i < 20 else 20) for i in range(30)]
        result = namespace['_driver']('moon_illum', 'Moon illumination', 'higher moon illumination', 'lower moon illumination', pairs)
        self.assertEqual(result['effect_pct'], 67)  # existing forecast weight preserved
        self.assertIn('20.0 vs 10.0 detections per recording day', result['statement'])
        self.assertNotIn('%', result['statement'])
        self.assertNotIn('×', result['statement'])
        self.assertEqual([b['days'] for b in result['buckets']], [10, 10, 10])
        self.assertEqual(result['buckets'][2]['min'], 20)
    def test_no_signal_for_flat_measurement(self):
        self.assertIsNone(namespace['_driver']('cloud','Cloud','higher','lower',[(50,i) for i in range(30)]))

if __name__ == '__main__': unittest.main()
