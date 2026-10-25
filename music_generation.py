"""ACE-Step instrumental generation, integrated with the existing music library."""
import copy
import json
import math
import queue
import re
import threading
import time
import uuid

PRESETS = {
    'horror': {'name': 'Terror', 'bpm': 60, 'prompt': 'Dark cinematic horror underscore, sparse low piano, ominous sustained strings, unsettling ambient drones, slow rising tension, restrained percussion, background soundtrack for spoken narration'},
    'suspense': {'name': 'Suspense', 'bpm': 80, 'prompt': 'Cinematic suspense underscore, muted ticking percussion, pulsing low synth, tense strings, gradual tension build, subtle dynamics, background soundtrack for spoken narration'},
    'mystery': {'name': 'Mistério', 'bpm': 75, 'prompt': 'Mysterious cinematic underscore, delicate minor-key piano, soft sustained strings, subtle investigative atmosphere, spacious arrangement, background soundtrack for spoken narration'},
    'emotional': {'name': 'Emocional', 'bpm': 70, 'prompt': 'Emotional cinematic underscore, gentle warm piano, soft strings, tender hopeful progression, delicate dynamics, spacious arrangement, background soundtrack for spoken narration'},
}
ACTIVE = ('queued', 'waiting', 'running', 'cancelling')


def install(p):
    path = p.ROOT / 'workflow_music.json'
    state_lock = threading.RLock()
    pending = queue.Queue()
    worker_thread = None
    jobs = p._load('music_generations.json', {})
    if not isinstance(jobs, dict):
        jobs = {}
    for job in jobs.values():
        if job.get('status') in ACTIVE:
            job.update(status='error', error='Geração interrompida pelo reinício do servidor. Gere novamente.')

    def save():
        with state_lock:
            p._save('music_generations.json', jobs)

    def update(job, **values):
        with state_lock:
            job.update(values, updated=p.now_str())
            save()

    def public(job):
        result = copy.deepcopy(job)
        if result.get('file'):
            result['url'] = '/media/music/' + p.urllib.parse.quote(result['file'], safe='')
        return result

    def load_workflow():
        if not path.is_file():
            raise RuntimeError('Workflow de música não encontrado: workflow_music.json')
        try:
            workflow = json.loads(path.read_text(encoding='utf-8-sig'))
            expected = {'94': 'TextEncodeAceStepAudio1.5', '97': 'CheckpointLoaderSimple',
                        '98': 'EmptyAceStep1.5LatentAudio', '104': 'SaveAudioMP3'}
            if any(workflow[node]['class_type'] != kind for node, kind in expected.items()):
                raise ValueError('Nós ACE-Step incompatíveis')
            return workflow
        except (ValueError, KeyError, TypeError) as exc:
            raise RuntimeError('Workflow de música inválido: ' + str(exc)) from exc

    def preflight():
        workflow = load_workflow()
        info = p.external(p.COMFY, '/object_info', timeout=30)
        missing = sorted({node['class_type'] for node in workflow.values()} - set(info))
        if missing:
            raise RuntimeError('Nós ausentes no ComfyUI: ' + ', '.join(missing))
        model = workflow['97']['inputs']['ckpt_name']
        schema = info['CheckpointLoaderSimple']['input']['required']['ckpt_name']
        choices = schema[0] if isinstance(schema[0], list) else schema[1].get('options', [])
        if model not in choices:
            raise RuntimeError('Modelo ACE-Step não disponível no ComfyUI: ' + model)
        for node in workflow.values():
            required = info[node['class_type']].get('input', {}).get('required', {})
            absent = set(required) - set(node['inputs'])
            if absent:
                raise RuntimeError(node['class_type'] + ': parâmetros ausentes: ' + ', '.join(sorted(absent)))
        return {'available': True, 'presets': PRESETS, 'model': model,
                'min_seconds': 10, 'max_seconds': 180, 'max_active': 4}

    def number(data, key, default, low, high):
        value = data.get(key, default)
        if isinstance(value, bool):
            raise ValueError('Valor inválido: ' + key)
        try:
            value = float(value)
        except (ValueError, TypeError):
            raise ValueError('Valor inválido: ' + key)
        if not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f'{key} precisa estar entre {low} e {high}')
        return value

    def build(job):
        workflow = load_workflow()
        encoder = workflow['94']['inputs']
        encoder.update(tags=job['prompt'] + ', instrumental, no vocals, no singing, no spoken words',
                       lyrics='', language='unknown', duration=job['seconds'], bpm=job['bpm'], seed=job['seed'])
        workflow['98']['inputs'].update(seconds=job['seconds'], batch_size=1)
        workflow['3']['inputs']['seed'] = job['seed']
        workflow['104']['inputs']['filename_prefix'] = 'HistoriasStudio/music/' + job['id']
        return workflow

    def execute(job, workflow):
        response = p.external(p.COMFY, '/prompt', {'prompt': workflow, 'client_id': p.CLIENT_ID}, timeout=30)
        if response.get('node_errors') or not response.get('prompt_id'):
            raise RuntimeError('ComfyUI recusou a música: ' + json.dumps(response.get('node_errors', response), ensure_ascii=False)[:1000])
        pid = response['prompt_id']
        update(job, prompt_id=pid, status='running', detail='Gerando trilha instrumental no ComfyUI')
        deadline = time.monotonic() + 1800
        deleted = False
        while True:
            cancelled = job.get('cancel_requested', False)
            if cancelled:
                update(job, status='cancelling', detail='Cancelando; uma etapa já em execução precisa terminar') if job['status'] != 'cancelling' else None
                if not deleted:
                    p.external(p.COMFY, '/queue', {'delete': [pid]}, timeout=15, raw=True)
                    deleted = True
                running = p.external(p.COMFY, '/queue', timeout=15).get('queue_running', [])
                if not any(len(item) > 1 and item[1] == pid for item in running):
                    raise InterruptedError('Geração cancelada')
            history = p.external(p.COMFY, '/history/' + p.urllib.parse.quote(pid, safe=''), timeout=30)
            if pid in history:
                result = history[pid]
                if cancelled:
                    raise InterruptedError('Geração cancelada')
                if result.get('status', {}).get('status_str') == 'error':
                    raise RuntimeError('ACE-Step falhou: ' + p._comfy_error(result))
                if result.get('status', {}).get('completed', True):
                    return result.get('outputs', {})
            if time.monotonic() > deadline:
                raise TimeoutError('Tempo limite de 30 minutos excedido na geração de música')
            time.sleep(2)

    def produce(job):
        gpu_lock = p.MEDIA_GPU_LOCK
        update(job, status='waiting', detail='Aguardando a vez na GPU')
        while not gpu_lock.acquire(timeout=.5):
            if job.get('cancel_requested'):
                raise InterruptedError('Geração cancelada')
        try:
            deadline = time.monotonic() + 1800
            while True:
                if job.get('cancel_requested'):
                    raise InterruptedError('Geração cancelada')
                queued = p.external(p.COMFY, '/queue', timeout=15)
                if not queued.get('queue_running') and not queued.get('queue_pending'):
                    break
                if time.monotonic() > deadline:
                    raise TimeoutError('O ComfyUI permaneceu ocupado por mais de 30 minutos')
                time.sleep(2)
            preflight()
            p.prepare_audio_generation_gpu()
            if job.get('cancel_requested'):
                raise InterruptedError('Geração cancelada')
            outputs = execute(job, build(job))
            files = p.comfy_files(outputs, ('.mp3',))
            if not files:
                raise RuntimeError('O workflow terminou sem devolver um MP3')
            blob = p.comfy_fetch(files[0])
            if not blob or len(blob) > 40_000_000:
                raise RuntimeError('Áudio gerado vazio ou maior que 40 MB')
            folder = p.DATA / 'music_generation_work' / job['id']
            folder.mkdir(parents=True, exist_ok=True)
            temporary = folder / 'result.mp3'
            temporary.write_bytes(blob)
            duration = p.ffprobe_duration(temporary)
            if not duration:
                raise RuntimeError('FFprobe não conseguiu validar a duração da música gerada')
            if job.get('cancel_requested'):
                raise InterruptedError('Geração cancelada')
            filename = 'ace_' + job['id'] + '.mp3'
            with p.LOCK:
                p.os.replace(temporary, p.MUSIC_DIR / filename)
                p.MUSIC_META[filename] = {'name': job['title'], 'tags': [job['preset'], 'instrumental', 'ace-step'],
                                          'duration': round(duration, 3), 'size': len(blob), 'source': 'ace-step-1.5',
                                          'generation': {key: job[key] for key in ('prompt', 'seconds', 'bpm', 'seed')}}
                p._save('music.json', p.MUSIC_META)
            update(job, status='done', detail='Pronta na biblioteca de músicas', file=filename,
                   duration=round(duration, 3), error=None)
        finally:
            gpu_lock.release()

    def worker():
        while True:
            jid = pending.get()
            job = jobs[jid]
            try:
                if job.get('cancel_requested'):
                    raise InterruptedError('Geração cancelada')
                produce(job)
            except InterruptedError:
                update(job, status='cancelled', detail='Geração cancelada', error=None)
            except Exception as exc:
                update(job, status='error', detail='Não foi possível gerar a música', error=str(exc)[:2000])
            finally:
                pending.task_done()

    def create(data):
        nonlocal worker_thread
        if not isinstance(data, dict):
            raise ValueError('Configuração de música inválida')
        preset = data.get('preset', 'horror')
        if preset not in (*PRESETS, 'custom'):
            raise ValueError('Perfil de música inválido')
        defaults = PRESETS.get(preset, {})
        prompt = str(data.get('prompt') or defaults.get('prompt') or '').strip()
        if not 10 <= len(prompt) <= 3000:
            raise ValueError('Descreva a música com 10 a 3.000 caracteres')
        seconds = number(data, 'seconds', 40, 10, 180)
        bpm = number(data, 'bpm', defaults.get('bpm', 70), 30, 200)
        if not bpm.is_integer():
            raise ValueError('O andamento precisa ser um número inteiro')
        seed = data.get('seed')
        seed = int.from_bytes(p.os.urandom(4), 'big') if seed in (None, '') else number(data, 'seed', 0, 0, 4294967295)
        if int(seed) != seed:
            raise ValueError('Seed precisa ser um número inteiro')
        # Report missing nodes/models before adding a job to the GPU queue.
        preflight()
        with state_lock:
            if sum(job.get('status') in ACTIVE for job in jobs.values()) >= 4:
                raise ValueError('Já existem quatro músicas em geração ou na fila. Aguarde uma terminar.')
            jid = uuid.uuid4().hex[:12]
            job = {'id': jid, 'title': str(data.get('title') or defaults.get('name') or 'Trilha instrumental').strip()[:100],
                   'prompt': prompt, 'preset': preset, 'seconds': seconds, 'bpm': int(bpm), 'seed': int(seed),
                   'status': 'queued', 'detail': 'Na fila de geração', 'created': p.now_str(), 'file': None,
                   'duration': None, 'error': None, 'cancel_requested': False}
            jobs[jid] = job
            save()
            pending.put(jid)
            if worker_thread is None or not worker_thread.is_alive():
                worker_thread = threading.Thread(target=worker, daemon=True, name='ace-step-music')
                worker_thread.start()
            return public(job)

    original_route = p.route
    def route(h, method):
        endpoint = p.urllib.parse.urlparse(h.path).path
        match = re.fullmatch(r'/api/music/generation/([a-f0-9]{12})/cancel', endpoint)
        if endpoint not in ('/api/music/generation', '/api/music/generation/status') and not match:
            if endpoint == '/api/music' or re.fullmatch(r'/api/music/[^/]+/(meta|delete)', endpoint):
                with p.LOCK:
                    return original_route(h, method)
            return original_route(h, method)
        try:
            if method == 'GET' and endpoint.endswith('/status'):
                try:
                    h.send(200, preflight())
                except Exception as exc:
                    h.send(200, {'available': False, 'error': str(exc), 'presets': PRESETS})
            elif method == 'GET' and endpoint == '/api/music/generation':
                with state_lock:
                    h.send(200, [public(job) for job in list(jobs.values())[-30:][::-1]])
            elif method == 'POST' and endpoint == '/api/music/generation':
                h.send(202, create(p._read_json(h)))
            elif method == 'POST' and match:
                with state_lock:
                    job = jobs.get(match[1])
                    if not job:
                        raise ValueError('Geração não encontrada')
                    if job['status'] in ACTIVE:
                        job['cancel_requested'] = True
                        update(job, status='cancelled' if job['status'] == 'queued' else 'cancelling')
                    h.send(200, public(job))
            else:
                h.send(405, {'error': 'Método não permitido'})
        except (ValueError, TypeError) as exc:
            h.send(400, {'error': str(exc)})
        except Exception as exc:
            h.send(502, {'error': str(exc)})
        return True

    p.route = route
    p.generate_music = create
    p.music_generation_jobs = jobs
    p.build_music_workflow = build
