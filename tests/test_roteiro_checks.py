"""Travas automáticas do roteiro (narrative.local_checks)."""
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from narrative import local_checks
DUR = {'30-40': {'seconds': 35}, '60-90': {'seconds': 75}}
PT = 'Ana viu o cartaz e sentiu que o mundo parou quando percebeu que era o seu cachorro.'


def sc(text):
    return {'narration': text}


class Checks(unittest.TestCase):
    def kinds(self, script, cfg):
        issues, failed = local_checks(script, cfg, DUR)
        return [i['problem'] for i in issues], failed

    def test_good_script_passes(self):
        s = {'scenes': [sc(PT), sc('Ela correu até a praça com a foto na mão.'), sc('Lá estava Carlos, que procurava o cão havia semanas.'), sc('Os dois sorriram quando Rex pulou no colo dele.')]}
        probs, failed = self.kinds(s, {'duration': '30-40', 'language': 'pt-BR'})
        self.assertEqual(probs, []); self.assertEqual(failed, set())

    def test_too_few_scenes(self):
        probs, failed = self.kinds({'scenes': [sc(PT), sc(PT + ' Fim.')]}, {'duration': '60-90', 'language': 'pt-BR'})
        self.assertTrue(any('Poucas cenas' in p for p in probs)); self.assertIn('read_aloud', failed)

    def test_wrong_language(self):
        en = 'She saw the poster and she knew that it was her dog and they were there with the man.'
        probs, failed = self.kinds({'scenes': [sc(en)] * 4}, {'duration': '30-40', 'language': 'pt-BR'})
        self.assertIn('natural_language', failed)

    def test_cta_inside_story(self):
        probs, failed = self.kinds({'scenes': [sc(PT), sc(PT), sc('E não esqueça: se inscreva no canal!'), sc(PT + ' Fim')]}, {'duration': '30-40', 'language': 'pt-BR'})
        self.assertTrue(any('inscreva' in p for p in probs))

    def test_long_scene_warning(self):
        probs, _ = self.kinds({'scenes': [sc(' '.join(['palavra'] * 45)), sc(PT), sc(PT + ' a'), sc(PT + ' b')]}, {'duration': '30-40', 'language': 'pt-BR'})
        self.assertTrue(any('longa demais' in p for p in probs))

    def test_cta_scene_ignored(self):
        s = {'scenes': [sc(PT), sc(PT + ' x'), sc(PT + ' y'), sc(PT + ' z'), {'narration': 'Siga o canal!', 'cta': True}]}
        probs, _ = self.kinds(s, {'duration': '30-40', 'language': 'pt-BR'})
        self.assertFalse(any('inscreva' in p.lower() or 'siga' in p.lower() for p in probs))


if __name__ == '__main__':
    unittest.main()
