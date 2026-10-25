"""Run: python tests/test_music_generation.py (FFmpeg and FFprobe on PATH)."""
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pipeline as p


class MusicGenerationTests(unittest.TestCase):
    def setUp(self):
        temporary_parent = Path.cwd() / 'work'
        temporary_parent.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=temporary_parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data, self.music = self.root / 'data', self.root / 'music'
        self.data.mkdir(); self.music.mkdir()
        sample = self.root / 'sample.mp3'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                        'sine=frequency=110:duration=1', '-c:a', 'libmp3lame', str(sample)], check=True)
        self.blob = sample.read_bytes()
        workflow = json.loads((p.ROOT / 'workflow_music.json').read_text(encoding='utf-8'))
        self.info = {n['class_type']: {'input': {'required': {key: ['ANY'] for key in n['inputs']}}} for n in workflow.values()}
        self.info['CheckpointLoaderSimple']['input']['required']['ckpt_name'] = [[workflow['97']['inputs']['ckpt_name']]]
        self.submitted = []
        self.reject = False
        self.no_audio = False
        self.gpu_lock = threading.Lock()
        p.music_generation_jobs.clear()
        for name, value in [('DATA', self.data), ('MUSIC_DIR', self.music), ('MUSIC_META', {}),
                            ('MEDIA_GPU_LOCK', self.gpu_lock), ('prepare_audio_generation_gpu', lambda: None),
                            ('external', self.external)]:
            mock = patch.object(p, name, value)
            mock.start(); self.addCleanup(mock.stop)

    def external(self, base, endpoint, data=None, **kwargs):
        if endpoint == '/object_info': return copy.deepcopy(self.info)
        if endpoint == '/queue': return {'queue_running': [], 'queue_pending': []}
        if endpoint == '/prompt':
            self.submitted.append(copy.deepcopy(data['prompt']))
            if self.reject: return {'node_errors': {'94': {'error': 'fixture failure'}}}
            return {'prompt_id': 'fixture-prompt'}
        if endpoint.startswith('/history/'):
            audio = {} if self.no_audio else {'104': {'audio': [{'filename': 'fixture.mp3', 'type': 'output', 'subfolder': 'music'}]}}
            return {'fixture-prompt': {'status': {'completed': True, 'status_str': 'success'}, 'outputs': audio}}
        if endpoint.startswith('/view?'): return self.blob, 'audio/mpeg'
        raise AssertionError(endpoint)

    def wait(self, jid, wanted=None):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            class Handler:
                path = '/api/music/generation'
                def send(self, code, data): self.data = data
            handler = Handler()
            p.route(handler, 'GET')
            job = next(j for j in handler.data if j['id'] == jid)
            if wanted and job['status'] == wanted: return job
            if not wanted and job['status'] not in ('queued', 'waiting', 'running', 'cancelling'): return job
            threading.Event().wait(.02)
        self.fail('worker did not reach expected state')

    def test_instrumental_workflow_and_library(self):
        job = p.generate_music({'preset': 'horror', 'title': 'Terror de teste', 'seconds': 20, 'bpm': 60, 'seed': 42})
        result = self.wait(job['id'])
        self.assertEqual(result['status'], 'done', result.get('error'))
        workflow = self.submitted[0]
        self.assertEqual(workflow['94']['inputs']['lyrics'], '')
        self.assertEqual(workflow['94']['inputs']['language'], 'unknown')
        self.assertIn('no vocals', workflow['94']['inputs']['tags'])
        self.assertEqual(workflow['94']['inputs']['duration'], 20)
        self.assertEqual(workflow['98']['inputs']['seconds'], 20)
        self.assertEqual(workflow['3']['inputs']['seed'], workflow['94']['inputs']['seed'])
        self.assertEqual(workflow['98']['inputs']['batch_size'], 1)
        self.assertTrue((self.music / result['file']).is_file())
        self.assertGreater(result['duration'], 0)
        library = p.list_music()
        self.assertEqual(library[0]['name'], 'Terror de teste')
        self.assertEqual(library[0]['file'], result['file'])
        stored = json.loads((self.data / 'music_generations.json').read_text(encoding='utf-8'))
        self.assertEqual(stored[job['id']]['status'], 'done')
        self.assertEqual(p.MUSIC_META[result['file']]['generation']['seed'], 42)

    def test_invalid_controls_are_rejected(self):
        for values in ({'seconds': 0}, {'seconds': 181}, {'bpm': 60.5}, {'bpm': 'nan'},
                       {'seed': -1}, {'seed': 2.5}, {'seconds': True}, {'preset': 'unknown'}):
            with self.subTest(values=values), self.assertRaises(ValueError): p.generate_music(values)
        self.assertFalse(self.submitted)

    def test_missing_checkpoint_and_node_are_reported(self):
        self.info['CheckpointLoaderSimple']['input']['required']['ckpt_name'] = [[]]
        with self.assertRaisesRegex(RuntimeError, 'Modelo ACE-Step'): p.generate_music({})
        self.info.pop('TextEncodeAceStepAudio1.5')
        with self.assertRaisesRegex(RuntimeError, 'Nós ausentes'): p.generate_music({})
        self.assertFalse(p.music_generation_jobs)

    def test_comfy_rejection_is_visible(self):
        self.reject = True
        job = p.generate_music({})
        result = self.wait(job['id'])
        self.assertEqual(result['status'], 'error')
        self.assertIn('recusou', result['error'])
        self.assertFalse(list(self.music.iterdir()))

    def test_missing_audio_is_not_added_to_library(self):
        self.no_audio = True
        job = p.generate_music({})
        result = self.wait(job['id'])
        self.assertEqual(result['status'], 'error')
        self.assertIn('sem devolver um MP3', result['error'])
        self.assertFalse(list(self.music.iterdir()))

    def test_gpu_wait_and_cancel_do_not_submit_work(self):
        self.gpu_lock.acquire()
        try:
            job = p.generate_music({})
            self.wait(job['id'], 'waiting')
            self.assertFalse(self.submitted)
            class Handler:
                path = '/api/music/generation/' + job['id'] + '/cancel'
                def send(self, code, data): self.code, self.data = code, data
            handler = Handler()
            self.assertTrue(p.route(handler, 'POST'))
            self.assertEqual(handler.code, 200)
            self.assertEqual(self.wait(job['id'])['status'], 'cancelled')
            self.assertFalse(self.submitted)
        finally:
            self.gpu_lock.release()

    def test_audio_output_collection_preserves_existing_outputs(self):
        output = {'one': {'audio': [{'filename': 'music.mp3'}], 'images': [{'filename': 'frame.png'}]}}
        self.assertEqual(p.comfy_files(output, ('.mp3',)), [{'filename': 'music.mp3'}])
        self.assertEqual(p.comfy_files(output, ('.png',)), [{'filename': 'frame.png'}])


if __name__ == '__main__': unittest.main(verbosity=2)
