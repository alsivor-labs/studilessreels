"""Testes da trilha automática (score.py) com provedores simulados."""
import json, sys, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pipeline as p


class ScoreTests(unittest.TestCase):
    def setUp(self):
        self.orig = (p.llm_chat, p.comfy_run, p.comfy_fetch, p._upd)
        p._upd = lambda v, **kw: v.update(kw)
        self.script = {'title': 'T', 'summary': 'Uma comédia na cozinha', 'plan': {'genre': 'emotional', 'final_emotion': 'alívio'},
                       'scenes': [{'narration': 'a', 'emotion': 'caos'}, {'narration': 'b', 'emotion': 'alívio'}]}

    def tearDown(self):
        p.llm_chat, p.comfy_run, p.comfy_fetch, p._upd = self.orig

    def test_brief_from_llm(self):
        p.llm_chat = lambda *a, **k: (json.dumps({'tags': 'playful light comedy underscore, pizzicato strings, marimba, soft drums, builds then resolves', 'bpm': 300, 'keyscale': 'f MAJOR', 'mood': 'leve'}), 'teste')
        b = p.score_brief({'niche': 'x', 'language': 'pt-BR'}, self.script)
        self.assertEqual(b['bpm'], 140)               # limitado à faixa
        self.assertEqual(b['keyscale'], 'F major')    # normalizado

    def test_brief_fallback_by_genre(self):
        def boom(*a, **k): raise RuntimeError('offline')
        p.llm_chat = boom
        b = p.score_brief({'niche': 'x'}, self.script)
        self.assertIn('Emotional', b['tags'])
        self.assertEqual(b['source'], 'padrão do gênero')

    def test_generate_builds_workflow_with_exact_duration(self):
        seen = {}
        p.llm_chat = lambda *a, **k: (json.dumps({'tags': 'dark ambient drones, low piano, slow tension build, quiet ending', 'bpm': 60, 'keyscale': 'E minor'}), 'teste')
        def run(wf, **k):
            seen['wf'] = wf
            return {'104': {'audio': [{'filename': 'x.mp3', 'subfolder': '', 'type': 'output'}]}}
        p.comfy_run = run
        import subprocess
        mp3 = subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'sine=d=31', '-f', 'mp3', '-'], capture_output=True).stdout
        p.comfy_fetch = lambda item: mp3
        with tempfile.TemporaryDirectory() as d:
            v = {'id': 'abc', 'seed': 7}
            out = p.generate_score(v, {'niche': 'x'}, self.script, 28.4, Path(d), lambda: False)
            self.assertTrue(out.is_file())
        enc = seen['wf']['94']['inputs']
        self.assertEqual(seen['wf']['98']['inputs']['seconds'], 30)   # ceil(28.4 + 1.5)
        self.assertEqual(enc['keyscale'], 'E minor')
        self.assertIn('no vocals', enc['tags'])
        self.assertEqual(self.script['score']['bpm'], 60)


if __name__ == '__main__':
    unittest.main()
