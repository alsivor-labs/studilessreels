# -*- coding: utf-8 -*-
"""Histórias Studio — Séries automáticas (estilo FacelessReels).

Pipeline local de cada vídeo:
  1. Roteiro      -> Ollama (JSON com cenas, prompts de imagem e de movimento)
  2. Narração     -> VoiceStudio (um áudio por cena, para sincronizar legendas)
  3. Imagens      -> ComfyUI (workflow.json · Z-Image Turbo)
  4. Movimento    -> ComfyUI (workflow_video.json · LTX-2 image-to-video)
  5. Montagem     -> FFmpeg (cortes, legendas animadas, música, efeitos)

Somente biblioteca padrão do Python.
"""
import json, os, re, io, time, uuid, wave, random, shutil, threading, subprocess, math, datetime, base64, concurrent.futures, mimetypes
import urllib.request, urllib.parse, urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
VIDEOS_DIR = ROOT / 'videos'
MUSIC_DIR = ROOT / 'music'
EXPORT_DIR = ROOT / 'exportados'
STYLE_PREV = DATA / 'style_previews'
CAST_DIR = DATA / 'cast'
VOICE_PREV = DATA / 'voice_previews'
MUSIC_PREV = DATA / 'music_previews'
for _d in (DATA, VIDEOS_DIR, MUSIC_DIR, EXPORT_DIR, STYLE_PREV, VOICE_PREV, CAST_DIR, MUSIC_PREV):
    _d.mkdir(parents=True, exist_ok=True)

COMFY = os.getenv('COMFY_URL', 'http://127.0.0.1:8188').rstrip('/')
VOICE = os.getenv('VOICE_URL', 'http://127.0.0.1:3900').rstrip('/')
OLLAMA = os.getenv('OLLAMA_URL', 'http://127.0.0.1:11434').rstrip('/')
OPENAI_URL = os.getenv('OPENAI_URL', 'https://api.openai.com/v1').rstrip('/')
GEMINI_URL = os.getenv('GEMINI_URL', 'https://generativelanguage.googleapis.com').rstrip('/')
ELEVEN_URL = os.getenv('ELEVEN_URL', 'https://api.elevenlabs.io').rstrip('/')
KIE_URL = os.getenv('KIE_URL', 'https://api.kie.ai').rstrip('/')
KIE_UPLOAD_URL = os.getenv('KIE_UPLOAD_URL', 'https://kieai.redpandaai.co').rstrip('/')
FAL_URL = os.getenv('FAL_URL', 'https://queue.fal.run').rstrip('/')
REPLICATE_URL = os.getenv('REPLICATE_URL', 'https://api.replicate.com').rstrip('/')
CLIENT_ID = 'historias-studio-' + uuid.uuid4().hex[:8]

IMG_WF = json.loads((ROOT / 'workflow.json').read_text(encoding='utf-8'))
VID_WF_PATH = ROOT / 'workflow_video.json'
VID_WF = json.loads(VID_WF_PATH.read_text(encoding='utf-8')) if VID_WF_PATH.is_file() else None

FPS = 25
OUT_W, OUT_H = 1080, 1920
LOCK = threading.RLock()

# --------------------------------------------------------------------------- catálogos

LANGUAGES = [
    {'id': 'pt-BR', 'name': 'Português (Brasil)', 'flag': 'BR', 'llm': 'Brazilian Portuguese',
     'sample': 'Olá! Eu sou a voz que vai narrar as histórias da sua série. Vamos começar?'},
    {'id': 'en-US', 'name': 'English', 'flag': 'US', 'llm': 'English',
     'sample': 'Hi! I am the voice that will narrate the stories of your series. Shall we begin?'},
    {'id': 'es-ES', 'name': 'Español', 'flag': 'ES', 'llm': 'Spanish',
     'sample': '¡Hola! Soy la voz que va a narrar las historias de tu serie. ¿Empezamos?'},
    {'id': 'fr-FR', 'name': 'Français', 'flag': 'FR', 'llm': 'French',
     'sample': 'Bonjour ! Je suis la voix qui va raconter les histoires de ta série. On commence ?'},
    {'id': 'it-IT', 'name': 'Italiano', 'flag': 'IT', 'llm': 'Italian',
     'sample': 'Ciao! Sono la voce che racconterà le storie della tua serie. Iniziamo?'},
    {'id': 'de-DE', 'name': 'Deutsch', 'flag': 'DE', 'llm': 'German',
     'sample': 'Hallo! Ich bin die Stimme, die die Geschichten deiner Serie erzählt. Los geht\'s?'},
]
LANG = {l['id']: l for l in LANGUAGES}

DURATIONS = [
    {'id': '30-40', 'label': '30-40 segundos', 'seconds': 35, 'scenes': 7},
    {'id': '40-50', 'label': '40-50 segundos', 'seconds': 45, 'scenes': 9},
    {'id': '50-60', 'label': '50-60 segundos', 'seconds': 55, 'scenes': 11},
    {'id': '60-90', 'label': '60-90 segundos', 'seconds': 75, 'scenes': 14},
]
DUR = {d['id']: d for d in DURATIONS}

NEG_BASE = ('low quality, blurry, deformed face, bad anatomy, extra fingers, missing fingers, extra limbs, '
            'distorted hands, duplicate characters, bad proportions, text, letters, caption, watermark, logo, '
            'cropped head, oversaturated, noisy, grainy')

ART_STYLES = [
    {'id': 'animacao_3d', 'name': 'Animação 3D',
     'prompt': 'masterpiece, cinematic 3D animated feature film still, stylized 3D characters, expressive faces, soft global illumination, warm cinematic lighting, detailed textures, depth of field',
     'negative': 'anime, manga, 2d illustration, flat cartoon, photorealistic, live action'},
    {'id': 'modern_cartoon', 'name': 'Cartoon Moderno',
     'prompt': 'modern cartoon illustration, adult animated sitcom style, clean thick outlines, vibrant flat colors, exaggerated expressive faces, comedic timing, detailed background',
     'negative': 'photorealistic, 3d render, live action, anime'},
    {'id': 'comic', 'name': 'Quadrinhos',
     'prompt': 'comic book illustration, bold ink outlines, vibrant flat colors, cel shading, graphic novel panel art, dramatic composition',
     'negative': 'photorealistic, 3d render, live action, speech bubble'},
    {'id': 'creepy_comic', 'name': 'Quadrinhos Sombrios',
     'prompt': 'dark creepy comic illustration, heavy ink shadows, muted desaturated colors, eerie unsettling atmosphere, horror graphic novel art',
     'negative': 'bright cheerful colors, photorealistic, 3d render, speech bubble'},
    {'id': 'realista', 'name': 'Cinema Realista',
     'prompt': 'photorealistic cinematic film still, shot on 35mm, natural lighting, realistic skin texture, shallow depth of field, color graded',
     'negative': 'cartoon, anime, illustration, 3d render, painting'},
    {'id': 'anime', 'name': 'Anime',
     'prompt': 'high quality anime illustration, cel shading, detailed painted background, vibrant colors, expressive eyes, dynamic composition',
     'negative': 'photorealistic, 3d render, live action, western cartoon'},
    {'id': 'aquarela', 'name': 'Aquarela',
     'prompt': 'delicate watercolor painting, soft color washes, visible paper texture, gentle brush strokes, storybook illustration',
     'negative': 'photorealistic, 3d render, harsh outlines'},
    {'id': 'pintura', 'name': 'Pintura a Óleo',
     'prompt': 'classical oil painting, rich impasto textures, dramatic chiaroscuro lighting, museum quality fine art',
     'negative': 'photorealistic, 3d render, cartoon, anime'},
    {'id': 'massinha', 'name': 'Massinha',
     'prompt': 'claymation stop-motion style, handmade plasticine characters, visible fingerprints in clay, miniature handcrafted set, soft studio lighting',
     'negative': 'photorealistic, anime, 2d illustration'},
]
for _s in ART_STYLES:
    _s.setdefault('motion', '')
    _s.setdefault('preview_prompt', '')

# Estilos de legenda (renderizados em ASS pelo FFmpeg). Cores em hex RGB.
CAPTION_STYLES = [
    {'id': 'bold_stroke', 'name': 'Bold Stroke', 'font': 'Arial Black', 'size': 96, 'bold': 1, 'italic': 0,
     'color': '#FFFFFF', 'outline_color': '#000000', 'outline': 8, 'shadow': 0, 'case': 'upper', 'group': 1},
    {'id': 'red_highlight', 'name': 'Red Highlight', 'font': 'Arial Black', 'size': 86, 'bold': 1, 'italic': 0,
     'color': '#FFFFFF', 'outline_color': '#000000', 'outline': 6, 'shadow': 2, 'case': 'upper', 'group': 2,
     'stack': True, 'hl': {'mode': 'color', 'color': '#FF2D2D'}},
    {'id': 'sleek', 'name': 'Sleek', 'font': 'Arial Black', 'size': 82, 'bold': 1, 'italic': 0,
     'color': '#FFFFFF', 'outline_color': '#000000', 'outline': 0, 'shadow': 6, 'case': 'upper', 'group': 2,
     'stack': True},
    {'id': 'karaoke', 'name': 'Karaoke', 'font': 'Arial Black', 'size': 82, 'bold': 1, 'italic': 0,
     'color': '#FFFFFF', 'outline_color': '#000000', 'outline': 5, 'shadow': 2, 'case': 'upper', 'group': 2,
     'stack': True, 'hl': {'mode': 'box', 'color': '#7C3AED'}},
    {'id': 'majestic', 'name': 'Majestic', 'font': 'Impact', 'size': 104, 'bold': 0, 'italic': 1,
     'color': '#FFFFFF', 'outline_color': '#000000', 'outline': 3, 'shadow': 8, 'case': 'upper', 'group': 2,
     'stack': True},
    {'id': 'beast', 'name': 'Beast', 'font': 'Impact', 'size': 118, 'bold': 0, 'italic': 1,
     'color': '#FFFFFF', 'outline_color': '#000000', 'outline': 9, 'shadow': 3, 'case': 'upper', 'group': 1},
    {'id': 'elegant', 'name': 'Elegant', 'font': 'Georgia', 'size': 78, 'bold': 0, 'italic': 0,
     'color': '#FFFFFF', 'outline_color': '#000000', 'outline': 0, 'shadow': 4, 'case': 'upper', 'group': 3},
    {'id': 'pixel', 'name': 'Pixel', 'font': 'Consolas', 'size': 86, 'bold': 1, 'italic': 0,
     'color': '#FFFFFF', 'outline_color': '#000000', 'outline': 9, 'shadow': 0, 'case': 'upper', 'group': 1},
    {'id': 'clarity', 'name': 'Clarity', 'font': 'Segoe UI', 'size': 84, 'bold': 1, 'italic': 0,
     'color': '#FFFFFF', 'outline_color': '#000000', 'outline': 0, 'shadow': 5, 'case': 'lower', 'group': 3},
]
CAPTION = {c['id']: c for c in CAPTION_STYLES}

PLATFORMS = [
    {'id': 'tiktok', 'name': 'TikTok'},
    {'id': 'youtube', 'name': 'YouTube Shorts'},
    {'id': 'instagram', 'name': 'Instagram Reels'},
    {'id': 'facebook', 'name': 'Facebook Reels'},
]

DEFAULT_SETTINGS = {
    'ollama_model': '',          # vazio = escolhe automaticamente (prefere qwen3)
    'tts_model': 'tts-1',
    'lead_hours': 6,             # gera X horas antes do horário de publicação
    'image_width': 768,
    'image_height': 1344,
    'motion_max_frames': 121,    # LTX-2: 121 quadros = ~4,8 s a 25 fps (múltiplo de 8 + 1)
    'music_volume': 0.12,
    'motion_provider': 'comfyui',  # comfyui local | kie cloud
    'kie_motion_resolution': '720p',
    'keep_work_files': True,
    'animate_all_scenes': True,  # só para séries antigas, sem "tipo de movimento"
    # provedores de IA (padrão: tudo local)
    'script_provider': 'ollama',     # ollama | openai | gemini | compatible | kie
    'openai_key': '', 'openai_model': 'gpt-4o-mini',
    'gemini_key': '', 'gemini_model': 'gemini-2.5-flash',
    'kie_script_model': 'gpt-5-5',
    'compat_base_url': '', 'compat_key': '', 'compat_model': '',
    'voice_provider': 'voicestudio', # voicestudio | elevenlabs | kie
    'eleven_key': '', 'eleven_model': 'eleven_multilingual_v2',
    'kie_key': '', 'kie_model': 'google/gemini-3-8-flash-tts',
    'image_provider': 'comfyui',     # comfyui | openai | gemini | kie
    'openai_image_model': 'gpt-image-2', 'openai_image_quality': 'medium',
    'gemini_image_model': 'gemini-3.1-flash-image',
    'kie_image_model': 'google/imagen4-fast',
    'fal_image_model': 'fal-ai/flux/schnell',
    'replicate_image_model': 'black-forest-labs/flux-schnell',
    'fal_motion_model': 'fal-ai/wan/v2.2-a14b/image-to-video',
    'replicate_motion_model': 'wan-video/wan-2.2-i2v-fast',
    'fal_key': '', 'replicate_key': '',
    'image_parallel': 3,             # imagens simultâneas nos provedores em nuvem
}
SECRET_KEYS = ('openai_key', 'gemini_key', 'compat_key', 'eleven_key', 'kie_key', 'fal_key', 'replicate_key')
SCRIPT_PROVIDERS = {'ollama': 'Ollama (local)', 'openai': 'OpenAI', 'gemini': 'Google Gemini',
                    'compatible': 'Compatível com OpenAI', 'kie': 'Kie AI'}
VOICE_PROVIDERS = {'voicestudio': 'VoiceStudio (local)', 'elevenlabs': 'ElevenLabs', 'kie': 'Kie AI'}
IMAGE_PROVIDERS = {'comfyui': 'ComfyUI (local)', 'openai': 'OpenAI', 'gemini': 'Google Gemini', 'kie': 'Kie AI'}
IMAGE_PROVIDERS.update({'fal': 'fal.ai', 'replicate': 'Replicate'})
MOTION_PROVIDERS = {'comfyui': 'ComfyUI · LTX-2', 'kie': 'Kie AI · Wan 2.2',
                    'fal': 'fal.ai · Wan 2.2', 'replicate': 'Replicate · Wan 2.2'}

# --------------------------------------------------------------------------- persistência

def _load(name, default):
    p = DATA / name
    if p.is_file():
        try:
            return json.loads(p.read_text(encoding='utf-8'))
        except Exception:
            shutil.copy(p, p.with_suffix('.corrompido.json'))
    return default


def _save(name, obj):
    p = DATA / name
    tmp = p.with_suffix('.tmp')
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding='utf-8')
    os.replace(tmp, p)


SERIES = _load('series.json', {})
VIDEOS = _load('videos.json', {})
SETTINGS = dict(DEFAULT_SETTINGS, **_load('settings.json', {}))
# Estilos de arte editáveis pelo usuário (Configurações > Estilos de arte)
STYLES_LIST = _load('styles.json', None) or json.loads(json.dumps(ART_STYLES))


def styles_map():
    return {s['id']: s for s in STYLES_LIST}


def get_style(style_id):
    return styles_map().get(style_id) or STYLES_LIST[0]


def save_styles():
    with LOCK:
        _save('styles.json', STYLES_LIST)


def save_series():
    with LOCK:
        _save('series.json', SERIES)


def save_videos():
    with LOCK:
        _save('videos.json', VIDEOS)


def now_str():
    return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

# --------------------------------------------------------------------------- HTTP externo

def external(base, path, data=None, timeout=90, raw=False, headers=None, body=None, auth=True):
    if body is None and data is not None:
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
    hdrs = {'Authorization': 'Bearer local'} if auth else {}
    if data is not None:
        hdrs['Content-Type'] = 'application/json'
    hdrs.update(headers or {})
    req = urllib.request.Request(base + path, data=body, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = resp.read()
            if raw:
                return payload, resp.headers.get('Content-Type', 'application/octet-stream')
            parsed = json.loads(payload)
            if (base == KIE_URL or base.startswith(KIE_URL + '/')) and isinstance(parsed, dict) and parsed.get('code') not in (None, 200):
                raise RuntimeError('Kie AI: ' + str(parsed.get('msg') or parsed.get('message') or parsed.get('code')))
            return parsed
    except urllib.error.HTTPError as exc:
        detail = exc.read(1500).decode('utf-8', 'replace')
        for k in SECRET_KEYS:
            if SETTINGS.get(k):
                detail = detail.replace(SETTINGS[k], '***')
        raise RuntimeError(f'{base} respondeu HTTP {exc.code}: {detail}') from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f'Não foi possível conectar em {base} ({exc.reason}). O aplicativo está aberto?') from exc


def ffprobe_duration(path_or_blob):
    if not shutil.which('ffprobe'):
        return None
    if isinstance(path_or_blob, (bytes, bytearray)):
        r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of',
                            'default=noprint_wrappers=1:nokey=1', 'pipe:0'], input=path_or_blob,
                           capture_output=True, timeout=30)
    else:
        r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of',
                            'default=noprint_wrappers=1:nokey=1', str(path_or_blob)], capture_output=True, timeout=30)
    try:
        d = float(r.stdout.strip())
        return d if d > 0 else None
    except ValueError:
        return None


def audio_valid(blob):
    """Valida o áudio retornado pelo VoiceStudio e devolve (extensão, duração)."""
    if blob[:4] == b'RIFF' and blob[8:12] == b'WAVE':
        try:
            with wave.open(io.BytesIO(blob), 'rb') as w:
                if w.getnframes() == 0 or w.getframerate() <= 0:
                    raise ValueError('WAV vazio')
                return '.wav', w.getnframes() / w.getframerate()
        except Exception:
            d = ffprobe_duration(blob)
            if d:
                return '.wav', d
            raise RuntimeError('VoiceStudio retornou um WAV inválido ou sem áudio')
    if blob[:3] == b'ID3' or blob[:2] in (b'\xff\xfb', b'\xff\xf3', b'\xff\xf2'):
        d = ffprobe_duration(blob)
        if d:
            return '.mp3', d
        raise RuntimeError('Não foi possível validar o MP3. Verifique se o FFmpeg está instalado.')
    raise RuntimeError('O provedor de voz não retornou áudio reconhecível. Resposta: ' + blob[:300].decode('utf-8', 'replace'))

# --------------------------------------------------------------------------- serviços

def service_status():
    out = {}
    for name, base, path in (('comfyui', COMFY, '/system_stats'), ('ollama', OLLAMA, '/api/tags'),
                             ('voicestudio', VOICE, '/health')):
        try:
            external(base, path, timeout=4)
            out[name] = {'ok': True, 'url': base}
        except Exception as exc:
            out[name] = {'ok': False, 'url': base, 'error': str(exc)[:200]}
    out['ffmpeg'] = {'ok': bool(shutil.which('ffmpeg') and shutil.which('ffprobe'))}
    sp, vp = SETTINGS.get('script_provider', 'ollama'), SETTINGS.get('voice_provider', 'voicestudio')
    need = {'openai': 'openai_key', 'gemini': 'gemini_key', 'compatible': 'compat_base_url', 'kie': 'kie_key'}
    out['script_provider'] = {'id': sp, 'name': SCRIPT_PROVIDERS.get(sp, sp),
                              'ok': out['ollama']['ok'] if sp == 'ollama' else bool(SETTINGS.get(need.get(sp, ''), '') or (sp == 'kie' and SETTINGS.get('compat_key')))}
    ip = SETTINGS.get('image_provider', 'comfyui')
    image_key = {'openai': 'openai_key', 'gemini': 'gemini_key', 'kie': 'kie_key',
                 'fal': 'fal_key', 'replicate': 'replicate_key'}.get(ip)
    out['image_provider'] = {'id': ip, 'name': IMAGE_PROVIDERS.get(ip, ip),
                             'ok': out['comfyui']['ok'] if ip == 'comfyui' else bool(SETTINGS.get(image_key or ''))}
    out['voice_provider'] = {'id': vp, 'name': VOICE_PROVIDERS.get(vp, vp),
                             'ok': out['voicestudio']['ok'] if vp == 'voicestudio' else bool(SETTINGS.get('kie_key' if vp == 'kie' else 'eleven_key'))}
    mp = SETTINGS.get('motion_provider', 'comfyui')
    motion_key = {'kie': 'kie_key', 'fal': 'fal_key', 'replicate': 'replicate_key'}.get(mp, '')
    out['motion_provider'] = {'id': mp, 'name': MOTION_PROVIDERS.get(mp, mp),
                              'ok': bool(SETTINGS.get(motion_key) or (mp == 'kie' and SETTINGS.get('compat_key')))
                              if mp in ('kie', 'fal', 'replicate') else VID_WF is not None}
    out['motion_workflow'] = {'ok': VID_WF is not None}
    return out


def ollama_models():
    d = external(OLLAMA, '/api/tags', timeout=8)
    return [m.get('name') or m.get('model') for m in d.get('models', []) if m.get('name') or m.get('model')]


def pick_ollama_model():
    if SETTINGS.get('ollama_model'):
        return SETTINGS['ollama_model']
    models = ollama_models()
    if not models:
        raise RuntimeError('Nenhum modelo instalado no Ollama. Rode por exemplo: ollama pull qwen3:8b')
    for pref in ('qwen3:8b', 'qwen3:14b', 'qwen3', 'qwen2.5', 'qwen'):
        for m in models:
            if pref in m:
                return m
    return models[0]

# --------------------------------------------------------------------------- ComfyUI

def comfy_upload(blob, name):
    boundary = uuid.uuid4().hex
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{name}"\r\n'
            f'Content-Type: image/png\r\n\r\n').encode() + blob + (
        f'\r\n--{boundary}\r\nContent-Disposition: form-data; name="overwrite"\r\n\r\ntrue\r\n'
        f'--{boundary}--\r\n').encode()
    r = external(COMFY, '/upload/image', timeout=60, body=body,
                 headers={'Content-Type': f'multipart/form-data; boundary={boundary}'})
    return (r.get('subfolder') + '/' if r.get('subfolder') else '') + r['name']


def _comfy_error(result):
    for msg in result.get('status', {}).get('messages', []):
        if isinstance(msg, list) and len(msg) > 1 and msg[0] == 'execution_error':
            info = msg[1]
            return f"{info.get('node_type', '')}: {info.get('exception_message', '')}".strip()
    return str(result.get('status', {}))[-400:]


def comfy_run(workflow, timeout=3600, cancelled=lambda: False):
    r = external(COMFY, '/prompt', {'prompt': workflow, 'client_id': CLIENT_ID}, timeout=30)
    if r.get('node_errors'):
        raise RuntimeError('ComfyUI recusou o workflow: ' + json.dumps(r['node_errors'], ensure_ascii=False)[:600])
    pid = r['prompt_id']
    end = time.time() + timeout
    while time.time() < end:
        if cancelled():
            try:
                external(COMFY, '/queue', {'delete': [pid]}, timeout=10)
            except Exception:
                pass
            raise InterruptedError('cancelado')
        hist = external(COMFY, '/history/' + urllib.parse.quote(pid), timeout=30)
        if pid in hist:
            res = hist[pid]
            st = res.get('status', {})
            if st.get('status_str') == 'error':
                raise RuntimeError('Erro no ComfyUI — ' + _comfy_error(res))
            if st.get('completed', True) and res.get('outputs'):
                return res['outputs']
        time.sleep(2)
    raise TimeoutError('Tempo limite aguardando o ComfyUI')


def comfy_files(outputs, exts):
    files = []
    for out in outputs.values():
        for key in ('videos', 'gifs', 'images', 'video', 'animated', 'audio', 'audios'):
            for item in out.get(key, []) or []:
                if isinstance(item, dict) and item.get('filename', '').lower().endswith(exts):
                    files.append(item)
    return files


def comfy_fetch(item):
    q = urllib.parse.urlencode({'filename': item['filename'], 'subfolder': item.get('subfolder', ''),
                                'type': item.get('type', 'output')})
    blob, _ = external(COMFY, '/view?' + q, timeout=180, raw=True)
    return blob


def generate_image(prompt, negative, seed, prefix, cancelled=lambda: False):
    wf = json.loads(json.dumps(IMG_WF))
    wf['67']['inputs']['text'] = prompt
    wf['71']['inputs']['text'] = negative
    wf['68']['inputs'].update(width=int(SETTINGS['image_width']), height=int(SETTINGS['image_height']), batch_size=1)
    wf['70']['inputs']['seed'] = int(seed)
    wf['9']['inputs']['filename_prefix'] = prefix
    outs = comfy_run(wf, timeout=1800, cancelled=cancelled)
    files = comfy_files(outs, ('.png', '.jpg', '.jpeg', '.webp'))
    if not files:
        raise RuntimeError('O workflow de imagem terminou sem imagens')
    return comfy_fetch(files[0])


def _to_png(blob):
    """Converte qualquer imagem (jpeg/webp/png) em PNG usando o FFmpeg."""
    if blob[:8] == b'\x89PNG\r\n\x1a\n':
        return blob
    r = subprocess.run(['ffmpeg', '-v', 'error', '-i', 'pipe:0', '-frames:v', '1', '-f', 'image2pipe', '-c:v', 'png',
                        'pipe:1'], input=blob, capture_output=True, timeout=60)
    if r.returncode != 0 or not r.stdout:
        raise RuntimeError('A imagem recebida não pôde ser lida')
    return r.stdout


def _find_b64_image(obj):
    """Procura a primeira imagem em base64 numa resposta JSON (formatos diferentes do Gemini)."""
    if isinstance(obj, dict):
        for k in ('output_image', 'inlineData', 'inline_data'):
            if isinstance(obj.get(k), dict) and obj[k].get('data'):
                return obj[k]['data']
        if obj.get('type') == 'image' and isinstance(obj.get('data'), str) and len(obj['data']) > 200:
            return obj['data']
        if isinstance(obj.get('bytesBase64Encoded'), str):
            return obj['bytesBase64Encoded']
        for v in obj.values():
            r = _find_b64_image(v)
            if r:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _find_b64_image(v)
            if r:
                return r
    return None


def _retry(fn, tries=4):
    for k in range(tries):
        try:
            return fn()
        except RuntimeError as exc:
            msg = str(exc)
            temporary = any(f'HTTP {c}' in msg for c in (429, 500, 502, 503, 504)) or 'conectar' in msg
            if not temporary or k == tries - 1:
                raise
            time.sleep((5, 15, 30, 60)[k])


def kie_task(model, inputs, timeout=900):
    task = kie_request('/api/v1/jobs/createTask', {'model': model, 'input': inputs}, timeout=90)
    task_id = (task.get('data') or {}).get('taskId') or (task.get('data') or {}).get('task_id')
    if not task_id:
        raise RuntimeError('Kie AI não retornou o identificador da tarefa')
    deadline = time.time() + timeout
    delay = 2
    while time.time() < deadline:
        time.sleep(delay)
        status = kie_request('/api/v1/jobs/recordInfo?' + urllib.parse.urlencode({'taskId': task_id}), timeout=60)
        info = status.get('data') or {}
        state = str(info.get('state') or '').lower()
        if state == 'success':
            result = info.get('resultJson') or {}
            if isinstance(result, str):
                try: result = json.loads(result)
                except Exception: result = {}
            return result
        if state in ('fail', 'failed', 'error'):
            raise RuntimeError('Kie AI falhou: ' + str(info.get('failMsg') or info.get('message') or 'erro desconhecido'))
        delay = min(10, delay + 1)
    raise TimeoutError('Kie AI demorou demais para concluir a geração')


def kie_image(prompt, negative=''):
    model = (SETTINGS.get('kie_image_model') or 'google/imagen4-fast').strip()
    result = kie_task(model, {'prompt': prompt, 'negative_prompt': negative, 'aspect_ratio': '9:16'})
    urls = result.get('resultUrls') or result.get('result_urls') or result.get('image_urls') or []
    if not urls and result.get('images'):
        urls = result['images']
    url = (urls[0] if isinstance(urls, list) and urls else urls) or result.get('url')
    if not url:
        raise RuntimeError('Kie AI concluiu a imagem sem devolver URL')
    with urllib.request.urlopen(url, timeout=120) as response:
        return _to_png(response.read())


def _first_media_url(value, keys=('url', 'uri')):
    if isinstance(value, str) and value.startswith(('https://', 'http://', 'data:')):
        return value
    if isinstance(value, dict):
        for key in keys:
            found = value.get(key)
            if isinstance(found, str) and found.startswith(('https://', 'http://', 'data:')):
                return found
        for child in value.values():
            found = _first_media_url(child, keys)
            if found:
                return found
    if isinstance(value, list):
        for child in value:
            found = _first_media_url(child, keys)
            if found:
                return found
    return None


def fal_queue(model, inputs, timeout=1800, cancelled=lambda: False):
    key = _need('fal_key', 'a chave do fal.ai')
    headers = {'Authorization': 'Key ' + key}
    base_path = '/' + model.strip().strip('/')
    accepted = external(FAL_URL, base_path, inputs, timeout=90, headers=headers, auth=False)
    request_id = accepted.get('request_id') or accepted.get('requestId')
    if not request_id:
        raise RuntimeError('fal.ai não retornou o identificador da tarefa')
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cancelled():
            raise InterruptedError('cancelado')
        time.sleep(3)
        status = external(FAL_URL, base_path + '/requests/' + urllib.parse.quote(str(request_id), safe='') + '/status',
                          timeout=45, headers=headers, auth=False)
        state = str(status.get('status') or '').upper()
        if state == 'COMPLETED':
            return external(FAL_URL, base_path + '/requests/' + urllib.parse.quote(str(request_id), safe=''),
                            timeout=60, headers=headers, auth=False)
        if state in ('FAILED', 'ERROR', 'CANCELLED'):
            raise RuntimeError('fal.ai falhou: ' + str(status.get('error') or status.get('detail') or state)[:400])
    raise TimeoutError('fal.ai demorou demais para concluir a geração')


def fal_image(prompt, negative='', seed=0, refs=(), ref_names=(), cancelled=lambda: False):
    model = (SETTINGS.get('fal_image_model') or 'fal-ai/flux/schnell').strip()
    text = cloud_prompt(prompt, negative, ref_names) if refs else cloud_prompt(prompt, negative, ())
    ans = fal_queue(model, {'prompt': text,
                            'image_size': {'width': int(SETTINGS.get('image_width') or 768),
                                           'height': int(SETTINGS.get('image_height') or 1344)},
                            'num_images': 1, 'output_format': 'png', 'seed': int(seed) % (2 ** 31)}, cancelled=cancelled)
    url = _first_media_url(ans.get('images') or ans, ('url', 'uri'))
    if not url:
        raise RuntimeError('fal.ai concluiu sem devolver uma imagem')
    with urllib.request.urlopen(url, timeout=120) as response:
        return _to_png(response.read())


def replicate_prediction(model, inputs, timeout=1800, cancelled=lambda: False):
    key = _need('replicate_key', 'o token da API do Replicate')
    model = model.strip().strip('/')
    if not re.fullmatch(r'[A-Za-z0-9_-]+/[A-Za-z0-9_.:-]+', model):
        raise RuntimeError('O modelo Replicate deve estar no formato proprietário/modelo')
    headers = {'Authorization': 'Bearer ' + key, 'Prefer': 'wait=60'}
    ans = external(REPLICATE_URL, '/v1/models/' + model + '/predictions', {'input': inputs},
                   timeout=95, headers=headers, auth=False)
    prediction_id = ans.get('id')
    if not prediction_id:
        raise RuntimeError('Replicate não retornou o identificador da tarefa')
    state = str(ans.get('status') or '').lower()
    deadline = time.time() + timeout
    while state not in ('succeeded', 'failed', 'canceled', 'cancelled') and time.time() < deadline:
        if cancelled():
            raise InterruptedError('cancelado')
        time.sleep(3)
        ans = external(REPLICATE_URL, '/v1/predictions/' + urllib.parse.quote(str(prediction_id), safe=''),
                       timeout=60, headers=headers, auth=False)
        state = str(ans.get('status') or '').lower()
    if state != 'succeeded':
        detail = ans.get('error') or state or 'tempo limite'
        raise RuntimeError('Replicate falhou: ' + str(detail)[:400])
    return ans.get('output')


def _replicate_image_input(path):
    # Replicate recommends data URLs for smaller inputs. Compress the local
    # frame first so image-to-video requests do not embed multi-megabyte PNGs.
    result = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-vf',
                             'scale=768:1344:force_original_aspect_ratio=decrease', '-q:v', '8',
                             '-f', 'image2pipe', '-vcodec', 'mjpeg', 'pipe:1'],
                            capture_output=True, timeout=60)
    if result.returncode or not result.stdout:
        raise RuntimeError('Não foi possível preparar a imagem para enviar ao Replicate')
    return 'data:image/jpeg;base64,' + base64.b64encode(result.stdout).decode('ascii')


def replicate_image(prompt, negative='', seed=0, refs=(), ref_names=(), cancelled=lambda: False):
    model = (SETTINGS.get('replicate_image_model') or 'black-forest-labs/flux-schnell').strip()
    text = cloud_prompt(prompt, negative, ref_names) if refs else cloud_prompt(prompt, negative, ())
    output = replicate_prediction(model, {'prompt': text, 'aspect_ratio': '9:16', 'output_format': 'png',
                                          'num_outputs': 1, 'seed': int(seed) % (2 ** 31)}, cancelled=cancelled)
    url = _first_media_url(output)
    if not url:
        raise RuntimeError('Replicate concluiu sem devolver uma imagem')
    with urllib.request.urlopen(url, timeout=120) as response:
        return _to_png(response.read())


def openai_image(prompt, refs=()):
    key = _need('openai_key', 'a chave da OpenAI')
    model = (SETTINGS.get('openai_image_model') or 'gpt-image-2').strip()
    size = '1024x1792' if model.startswith(('gpt-image-2', 'chatgpt-image')) else '1024x1536'
    quality = SETTINGS.get('openai_image_quality') or 'medium'
    hdr = {'Authorization': 'Bearer ' + key}
    if refs:
        boundary = uuid.uuid4().hex
        parts = []
        for k, v in (('model', model), ('prompt', prompt), ('size', size), ('quality', quality), ('n', '1')):
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
        for i, path in enumerate(refs[:16]):
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="image[]"; filename="ref{i}.png"\r\n'
                         f'Content-Type: image/png\r\n\r\n'.encode() + Path(path).read_bytes() + b'\r\n')
        body = b''.join(parts) + f'--{boundary}--\r\n'.encode()
        ans = _retry(lambda: external(OPENAI_URL, '/images/edits', timeout=600, body=body, auth=False,
                                      headers=dict(hdr, **{'Content-Type': f'multipart/form-data; boundary={boundary}'})))
    else:
        ans = _retry(lambda: external(OPENAI_URL, '/images/generations',
                                      {'model': model, 'prompt': prompt, 'size': size, 'quality': quality, 'n': 1},
                                      timeout=600, headers=hdr, auth=False))
    item = (ans.get('data') or [{}])[0]
    if item.get('b64_json'):
        return _to_png(base64.b64decode(item['b64_json']))
    if item.get('url'):
        with urllib.request.urlopen(item['url'], timeout=120) as r:
            return _to_png(r.read())
    raise RuntimeError('A OpenAI não devolveu imagem')


def gemini_image(prompt, refs=()):
    key = _need('gemini_key', 'a chave do Gemini')
    model = (SETTINGS.get('gemini_image_model') or 'gemini-3.1-flash-image').strip()
    hdr = {'x-goog-api-key': key}
    imgs = [base64.b64encode(Path(p).read_bytes()).decode() for p in refs[:5]]
    if model.startswith('imagen'):
        ans = _retry(lambda: external(GEMINI_URL, f'/v1beta/models/{model}:predict', {
            'instances': [{'prompt': prompt}], 'parameters': {'sampleCount': 1, 'aspectRatio': '9:16'}},
            timeout=600, headers=hdr, auth=False))
    else:
        try:   # API de Interações (documentação atual)
            ans = _retry(lambda: external(GEMINI_URL, '/v1beta/interactions', {
                'model': model,
                'input': [{'type': 'text', 'text': prompt}] + [{'type': 'image', 'mime_type': 'image/png', 'data': d} for d in imgs],
                'response_format': {'type': 'image', 'mime_type': 'image/png', 'aspect_ratio': '9:16', 'image_size': '1K'}},
                timeout=600, headers=hdr, auth=False))
        except RuntimeError as exc:
            if not any(f'HTTP {c}' in str(exc) for c in (400, 404)):
                raise
            # formato clássico generateContent
            ans = _retry(lambda: external(GEMINI_URL, f'/v1beta/models/{urllib.parse.quote(model)}:generateContent', {
                'contents': [{'role': 'user', 'parts': [{'text': prompt}] + [{'inline_data': {'mime_type': 'image/png', 'data': d}} for d in imgs]}],
                'generationConfig': {'responseModalities': ['IMAGE'], 'imageConfig': {'aspectRatio': '9:16'}}},
                timeout=600, headers=hdr, auth=False))
    b64 = _find_b64_image(ans)
    if not b64:
        raise RuntimeError('O Gemini não devolveu imagem: ' + json.dumps(ans)[:300])
    return _to_png(base64.b64decode(b64))


def cloud_prompt(prompt, negative, ref_names):
    p = prompt
    if ref_names:
        lst = '; '.join(f'image {i + 1} = {n}' for i, n in enumerate(ref_names))
        p += (f'. Reference images attached ({lst}): draw these characters with EXACTLY the same face, hair, body, '
              'clothing and colours as in their reference image, in the art style described. Do not copy the reference '
              'pose or background.')
    neg = ', '.join(dict.fromkeys(x.strip() for x in negative.split(',') if x.strip()))[:400]
    return p + (f'. Avoid: {neg}.' if neg else '') + ' Vertical 9:16 frame. No text, letters, captions, logos or watermarks.'


def make_image(prompt, negative, seed, prefix, refs=(), ref_names=(), cancelled=lambda: False, provider=None):
    """Gera uma imagem no provedor configurado. `refs` = caminhos de imagens de referência (só nuvem)."""
    prov = provider or SETTINGS.get('image_provider') or 'comfyui'
    if prov == 'openai':
        return openai_image(cloud_prompt(prompt, negative, ref_names), list(refs))
    if prov == 'gemini':
        return gemini_image(cloud_prompt(prompt, negative, ref_names), list(refs))
    if prov == 'kie':
        return kie_image(cloud_prompt(prompt, negative, ref_names) if refs else prompt, negative)
    if prov == 'fal':
        return fal_image(prompt, negative, seed, refs, ref_names, cancelled)
    if prov == 'replicate':
        return replicate_image(prompt, negative, seed, refs, ref_names, cancelled)
    return generate_image(prompt, negative, seed, prefix, cancelled)


def supports_refs(provider=None):
    return (provider or SETTINGS.get('image_provider')) in ('openai', 'gemini')


def ltx_frames(seconds):
    mx = int(SETTINGS.get('motion_max_frames') or 121)
    n = int(math.ceil(seconds * FPS))
    n = max(49, min(mx, n))
    return ((n - 1 + 7) // 8) * 8 + 1 if ((n - 1 + 7) // 8) * 8 + 1 <= mx else ((mx - 1) // 8) * 8 + 1


def animate_image_kie(image_path, motion_prompt, seed, cancelled=lambda: False):
    if cancelled():
        raise InterruptedError('cancelado')
    image_url = kie_upload_image(image_path)
    result = kie_task('wan/2-2-a14b-image-to-video-turbo', {
        'image_url': image_url,
        'prompt': motion_prompt,
        'resolution': SETTINGS.get('kie_motion_resolution') or '720p',
        'aspect_ratio': '9:16',
        'enable_prompt_expansion': False,
        'seed': int(seed),
        'acceleration': 'none',
        'nsfw_checker': False,
    }, timeout=1800)
    urls = result.get('resultUrls') or result.get('result_urls') or result.get('video_urls') or []
    url = (urls[0] if isinstance(urls, list) and urls else urls) or result.get('url') or result.get('videoUrl') or result.get('video_url')
    if not url:
        raise RuntimeError('Kie AI concluiu a animação sem devolver URL do vídeo')
    if str(url).startswith('data:'):
        try: return base64.b64decode(str(url).split(',', 1)[1]), '.mp4'
        except Exception as exc: raise RuntimeError('Kie AI retornou vídeo base64 inválido') from exc
    req = urllib.request.Request(url, headers={'User-Agent': 'HistoriasStudio/1.0'})
    with urllib.request.urlopen(req, timeout=180) as response:
        blob = response.read()
    if len(blob) < 1000:
        raise RuntimeError('Kie AI retornou um arquivo de vídeo vazio')
    return blob, '.mp4'


def _download_media(url, timeout=180):
    if str(url).startswith('data:'):
        try:
            return base64.b64decode(str(url).split(',', 1)[1]), '.mp4'
        except Exception as exc:
            raise RuntimeError('O provedor retornou um arquivo base64 inválido') from exc
    req = urllib.request.Request(url, headers={'User-Agent': 'HistoriasStudio/1.0'})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        blob = response.read()
        mime = response.headers.get('Content-Type', '')
    if len(blob) < 1000:
        raise RuntimeError('O provedor retornou um arquivo de vídeo vazio')
    ext = '.webm' if 'webm' in mime.lower() or str(url).lower().split('?', 1)[0].endswith('.webm') else '.mp4'
    return blob, ext


def fal_animate_image(image_path, motion_prompt, seed, frames, cancelled=lambda: False):
    if cancelled():
        raise InterruptedError('cancelado')
    model = (SETTINGS.get('fal_motion_model') or 'fal-ai/wan/v2.2-a14b/image-to-video').strip()
    num_frames = max(17, min(161, int(round(max(1, frames) / FPS * 16))))
    inputs = {'image_url': _replicate_image_input(image_path), 'prompt': motion_prompt,
              'num_frames': num_frames, 'frames_per_second': 16, 'resolution': '480p',
              'aspect_ratio': 'auto', 'seed': int(seed) % (2 ** 31), 'enable_prompt_expansion': False}
    result = fal_queue(model, inputs, timeout=1800, cancelled=cancelled)
    url = _first_media_url(result.get('video') or result, ('url', 'uri'))
    if not url:
        raise RuntimeError('fal.ai concluiu a animação sem devolver URL do vídeo')
    return _download_media(url)


def replicate_animate_image(image_path, motion_prompt, seed, frames, cancelled=lambda: False):
    if cancelled():
        raise InterruptedError('cancelado')
    model = (SETTINGS.get('replicate_motion_model') or 'wan-video/wan-2.2-i2v-fast').strip()
    # The default Wan 2.2 I2V endpoint accepts 81-121 frames and uses vertical 480p.
    num_frames = max(81, min(121, int(round(max(1, frames) / FPS * 16))))
    output = replicate_prediction(model, {'image': _replicate_image_input(image_path), 'prompt': motion_prompt,
                                           'go_fast': True, 'num_frames': num_frames,
                                           'resolution': '480p', 'frames_per_second': 16,
                                           'sample_shift': 12}, timeout=1800, cancelled=cancelled)
    url = _first_media_url(output)
    if not url:
        raise RuntimeError('Replicate concluiu a animação sem devolver URL do vídeo')
    return _download_media(url)


def animate_image(image_path, motion_prompt, seed, frames, prefix, cancelled=lambda: False):
    if VID_WF is None:
        raise RuntimeError('workflow_video.json não encontrado na pasta do projeto')
    need = ['98', '92:3', '92:62', '92:11', '92:67', '75']
    if any(k not in VID_WF for k in need):
        raise RuntimeError('workflow_video.json não tem os nós esperados do LTX-2 (98, 92:3, 92:62, 92:11, 92:67, 75)')
    name = comfy_upload(Path(image_path).read_bytes(), prefix.replace('/', '_') + '.png')
    wf = json.loads(json.dumps(VID_WF))
    wf['98']['inputs']['image'] = name
    wf['92:3']['inputs']['text'] = motion_prompt
    wf['92:62']['inputs']['value'] = int(frames)
    wf['92:11']['inputs']['noise_seed'] = int(seed)
    wf['92:67']['inputs']['noise_seed'] = int(seed) + 1
    wf['75']['inputs']['filename_prefix'] = prefix
    outs = comfy_run(wf, timeout=3600, cancelled=cancelled)
    files = comfy_files(outs, ('.mp4', '.webm', '.mov', '.mkv', '.gif'))
    if not files:
        raise RuntimeError('O workflow LTX-2 terminou sem vídeo')
    return comfy_fetch(files[0]), Path(files[0]['filename']).suffix.lower()

# --------------------------------------------------------------------------- roteiro (Ollama)

def _extract_json(text):
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.S).strip()
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r'\{.*\}', text, flags=re.S)
        if m:
            return json.loads(m.group(0))
        raise


def _need(key, label):
    v = (SETTINGS.get(key) or '').strip()
    if not v:
        raise RuntimeError(f'Configure {label} em Configurações › Provedores de IA')
    return v


def llm_chat(prompt, temperature=0.8, json_mode=True, timeout=600):
    """Envia o prompt ao provedor de roteiro configurado e devolve (texto, nome_do_modelo)."""
    prov = SETTINGS.get('script_provider') or 'ollama'
    if prov == 'ollama':
        model = pick_ollama_model()
        body = {'model': model, 'stream': False, 'messages': [{'role': 'user', 'content': prompt}],
                'options': {'temperature': temperature, 'num_ctx': 16384}, 'keep_alive': 0}
        if json_mode:
            body['format'] = 'json'
        ans = external(OLLAMA, '/api/chat', body, timeout=timeout)
        return ans.get('message', {}).get('content', ''), 'Ollama · ' + model
    if prov == 'kie':
        key = (SETTINGS.get('kie_key') or SETTINGS.get('compat_key') or '').strip()
        if not key:
            key = _need('kie_key', 'a chave da API do Kie AI')
        model = (SETTINGS.get('kie_script_model') or 'gpt-5-5').strip()
        if model.startswith(('gpt-', 'gpt_')):
            path = '/codex/v1/responses'
            body = {'model': model, 'stream': False,
                    'input': [{'role': 'user', 'content': [{'type': 'input_text', 'text': prompt}]}]}
            if json_mode:
                body['text'] = {'format': {'type': 'json_object'}}
            ans = external(KIE_URL, path, body, timeout=timeout,
                           headers={'Authorization': 'Bearer ' + key}, auth=False)
            chunks = []
            for item in ans.get('output') or []:
                if item.get('type') == 'message':
                    chunks.extend(c.get('text', '') for c in item.get('content') or []
                                  if c.get('type') == 'output_text')
            return ''.join(chunks), SCRIPT_PROVIDERS[prov] + ' · ' + model
        path = '/' + urllib.parse.quote(model, safe='') + '/v1/chat/completions'
        body = {'model': model, 'messages': [{'role': 'user', 'content': prompt}], 'temperature': temperature}
        if json_mode:
            body['response_format'] = {'type': 'json_object'}
        try:
            ans = external(KIE_URL, path, body, timeout=timeout,
                           headers={'Authorization': 'Bearer ' + key}, auth=False)
        except RuntimeError as exc:
            msg = str(exc)
            if 'response_format' in msg and 'response_format' in body:
                body.pop('response_format', None)
            elif 'temperature' in msg and 'temperature' in body:
                body.pop('temperature', None)
            else:
                raise
            ans = external(KIE_URL, path, body, timeout=timeout,
                           headers={'Authorization': 'Bearer ' + key}, auth=False)
        return (ans.get('choices') or [{}])[0].get('message', {}).get('content') or '', SCRIPT_PROVIDERS[prov] + ' · ' + model
    if prov in ('openai', 'compatible'):
        if prov == 'openai':
            base, key = OPENAI_URL, _need('openai_key', 'a chave da OpenAI')
            model = (SETTINGS.get('openai_model') or 'gpt-4o-mini').strip()
        else:
            base = _need('compat_base_url', 'a URL do provedor compatível').rstrip('/')
            key, model = (SETTINGS.get('compat_key') or '').strip(), _need('compat_model', 'o modelo do provedor compatível')
        body = {'model': model, 'messages': [{'role': 'user', 'content': prompt}], 'temperature': temperature}
        if json_mode:
            body['response_format'] = {'type': 'json_object'}
        hdr = {'Authorization': 'Bearer ' + key} if key else {}
        try:
            ans = external(base, '/chat/completions', body, timeout=timeout, headers=hdr, auth=False)
        except RuntimeError as exc:
            msg = str(exc)
            if 'temperature' in msg:                 # alguns modelos só aceitam a temperatura padrão
                body.pop('temperature', None)
            elif 'response_format' in msg:          # provedores que não suportam modo JSON
                body.pop('response_format', None)
            else:
                raise
            ans = external(base, '/chat/completions', body, timeout=timeout, headers=hdr, auth=False)
        return ans['choices'][0]['message'].get('content') or '', SCRIPT_PROVIDERS[prov] + ' · ' + model
    if prov == 'gemini':
        key = _need('gemini_key', 'a chave do Gemini')
        model = (SETTINGS.get('gemini_model') or 'gemini-2.5-flash').strip()
        cfg = {'temperature': temperature}
        if json_mode:
            cfg['responseMimeType'] = 'application/json'
        ans = external(GEMINI_URL, f'/v1beta/models/{urllib.parse.quote(model)}:generateContent',
                       {'contents': [{'role': 'user', 'parts': [{'text': prompt}]}], 'generationConfig': cfg},
                       timeout=timeout, headers={'x-goog-api-key': key}, auth=False)
        cands = ans.get('candidates') or []
        if not cands:
            raise RuntimeError('O Gemini não devolveu resposta: ' + json.dumps(ans.get('promptFeedback', ans))[:300])
        parts = (cands[0].get('content') or {}).get('parts') or []
        return ''.join(p.get('text', '') for p in parts), 'Gemini · ' + model
    raise RuntimeError('Provedor de roteiro desconhecido: ' + prov)


def write_script(cfg, previous_titles, series=None):
    lang = LANG.get(cfg['language'], LANGUAGES[0])
    dur = DUR.get(cfg['duration'], DURATIONS[0])
    words = int(dur['seconds'] * (2.4 if lang['id'] == 'pt-BR' else 2.5))
    n = dur['scenes']
    example = (cfg.get('example') or '').strip()
    platforms = ', '.join(p['name'] for p in PLATFORMS if p['id'] in cfg.get('platforms', [])) or 'TikTok, Instagram Reels, YouTube Shorts'
    avoid = '\n'.join('- ' + t for t in previous_titles[-25:]) or '- (nenhum ainda)'
    continuous = bool(series and series.get('story_mode') == 'continuous')
    cast = (series or {}).get('cast') or []
    memory = (series or {}).get('episodes') or []
    bible = ''
    if cast:
        bible += ('RECURRING CAST (use these exact names and these exact looks every time they appear; you may add new '
                  'minor characters):\n' + '\n'.join(f"- {c['name']}: {c['look']}" for c in cast[:10]) + '\n')
    if continuous:
        bible += ('\nThis is a CONTINUOUS STORY. Continue the plot from the previous episodes, keeping every established fact '
                  'consistent. Start with a one-sentence recap only if it helps the hook.\nPREVIOUS EPISODES (oldest first):\n'
                  + ('\n'.join(f"{k}. {e['title']} — {e['summary']}" for k, e in enumerate(memory[-10:], 1)) or '(this is the first episode)') + '\n')
    prompt = f"""You are the head writer of a viral faceless short-video channel. Write ONE brand-new, original episode for the series below.

SERIES NICHE / BRIEF:
{cfg['niche']}

{('WRITING STYLE REFERENCE (imitate tone, rhythm and humour only; do NOT reuse its plot or jokes):' + chr(10) + example) if example else ''}

{bible}
RULES
- Narration language: {lang['llm']}. Title, description and hashtags also in {lang['llm']}.
- Target length: about {dur['seconds']} seconds read aloud (~{words} words in total), split into EXACTLY {n} scenes.
- Scene 1 must be a strong hook that grabs attention in the first 3 seconds.
- End with a twist or punchline, then a very short call to follow the page.
- The narration is read by ONE narrator voice. Write it the way a storyteller reads aloud. When characters talk, introduce them naturally (e.g. "the wife says: ..."). No script labels, no stage directions, no brackets, no emojis.
- Platforms: {platforms}.
- Do NOT repeat these previous episodes:
{avoid}
- Be factually careful: never invent dates, numbers or events presented as real facts. Keep ONE clear storyline from start to end.

VISUALS (always in English)
- Define every character once in "characters" with a fixed, very specific look (age, ethnicity, body, hair, face, clothing, colours). Reuse the cast looks above unchanged.
- "image_prompt": a single still frame for the exact moment spoken in this scene. Repeat the FULL look of every character that appears, plus setting, action, lighting and camera framing. Make each character's face, gaze, posture and gesture clearly show the emotion and reaction caused by this exact story event; match changes such as grief, joy, fear, relief or determination instead of using a generic neutral expression. At the climax, reveal or decisive turning point, show the strongest story-appropriate reaction and the immediate visual consequence, without changing the plot or exaggerating into an unrelated pose. If no character is visible, communicate the moment's emotional tone through the setting, action and lighting. Keep emotion consistent with the narration and scene-to-scene continuity. Vertical 9:16. Never ask for text, letters, captions or logos.
- "motion_prompt": what moves during ~5 seconds starting from that still frame: body actions, facial expression changes, natural blinking, camera movement (slow push-in, pan, handheld...). Keep the same character identity and environment.

Return ONLY valid JSON in this exact shape:
{{"title": "...", "description": "1-2 sentences", "hashtags": ["#...", "#..."],
  "summary": "2-3 sentences in {lang['llm']} with what happened in this episode (used as memory for the next one)",
  "characters": [{{"name": "...", "look": "..."}}],
  "scenes": [{{"narration": "...", "image_prompt": "...", "motion_prompt": "..."}}]}}"""
    last_err, model = None, SCRIPT_PROVIDERS.get(SETTINGS.get('script_provider'), 'IA')
    for attempt in range(3):
        content, model = llm_chat(prompt, 0.85 if attempt == 0 else 0.6)
        try:
            data = _extract_json(content)
            scenes = []
            for s in data.get('scenes', []):
                if not isinstance(s, dict):
                    continue
                narr = str(s.get('narration', '')).strip()
                img = str(s.get('image_prompt') or s.get('prompt') or '').strip()
                mot = str(s.get('motion_prompt') or s.get('motion') or '').strip()
                if narr and img:
                    scenes.append({'narration': narr, 'image_prompt': img,
                                   'motion_prompt': mot or 'Subtle natural movement, gentle breathing and blinking, slow cinematic push-in.'})
            if len(scenes) < 2:
                raise ValueError('poucas cenas')
            chars = [{'name': str(c['name']).strip()[:60], 'look': str(c['look']).strip()[:600]}
                     for c in data.get('characters', []) if isinstance(c, dict) and c.get('name') and c.get('look')]
            fixed = {c['name'].lower(): c for c in cast}
            for c in chars:                     # elenco fixo: a aparência salva sempre vence
                if c['name'].lower() in fixed:
                    c['look'] = fixed[c['name'].lower()]['look']
            tags = data.get('hashtags', [])
            if isinstance(tags, str):
                tags = tags.split()
            return {'title': str(data.get('title') or 'Episódio sem título').strip()[:140],
                    'description': str(data.get('description', '')).strip()[:600],
                    'hashtags': [('#' + str(t).lstrip('#')).replace(' ', '') for t in tags][:12],
                    'summary': str(data.get('summary', '')).strip()[:800],
                    'characters': chars[:8], 'scenes': scenes[:40], 'model': model}
        except Exception as exc:
            last_err = exc
    raise RuntimeError(f'{model} não retornou um roteiro válido: {last_err}')


def _char_slug(name):
    import unicodedata
    s = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', '_', s).strip('_')[:40] or 'personagem'


def scene_characters(script, scene):
    low = (scene.get('image_prompt', '') + ' ' + scene.get('narration', '')).lower()
    return [c for c in script.get('characters', []) if c['name'].lower() in low]


def ensure_sheet(char, cfg, folder, seed, cancelled):
    """Cria (uma vez) a ficha do personagem: imagem de referência usada em todas as cenas."""
    st = get_style(cfg['art_style'])
    path = folder / f"{_char_slug(char['name'])}__{st['id']}.png"
    if path.is_file():
        return path
    folder.mkdir(parents=True, exist_ok=True)
    prompt = (f"{st['prompt']}, character reference sheet of {char['name']}: {char['look']}. Single character, full body, "
              "standing, front view, neutral expression, plain light grey background, even lighting")
    path.write_bytes(make_image(prompt, NEG_BASE + ', ' + st.get('negative', ''), seed, 'HistoriasStudio/elenco',
                                cancelled=cancelled))
    return path


def build_image_prompt(cfg, script, scene):
    st = get_style(cfg['art_style'])
    p = scene['image_prompt']
    low = p.lower()
    extra = []
    for c in script.get('characters', []):
        if c['name'].lower() in low and c['look'][:40].lower() not in low:
            extra.append(f"{c['name']}: {c['look']}")
    if extra:
        p += '. ' + '. '.join(extra)
    narration = str(scene.get('narration', '')).strip()
    emotional_direction = (
        "Depict the exact spoken story moment, not a generic illustration. Make the visible character reaction unmistakable "
        "through facial expression, gaze, posture and gesture, and make it agree with the scene's emotion and narration. "
        "For a climax, revelation or turning point, capture the decisive instant and its strongest fitting emotional reaction. "
        "Use the environment and lighting to support the mood when no character is visible. Preserve the established character identity, "
        "story facts, setting and visual continuity; avoid neutral default faces and unrelated dramatic expressions."
    )
    if narration:
        emotional_direction += f" Spoken moment for emotional context: {narration}"
    return f"{st['prompt']}, {p}, {emotional_direction}, vertical 9:16 composition, full character visible, no text"


def build_motion_prompt(cfg, script, scene):
    st = get_style(cfg['art_style'])
    extra = (' ' + st['motion'].strip()) if st.get('motion', '').strip() else ''
    return (f"{scene['motion_prompt']}{extra} Consistent visual style: {st['prompt'].split(',')[0].strip()}. "
            "Continuous natural motion, consistent character identity, stable environment, physically believable movement.")

# --------------------------------------------------------------------------- legendas (ASS)

def _ass_color(hexrgb, alpha=0):
    h = hexrgb.lstrip('#')
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f'&H{alpha:02X}{b}{g}{r}'.upper()


def _ass_time(t):
    t = max(0.0, t)
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f'{h}:{m:02d}:{s:02d}.{cs:02d}'


def _ass_text(w):
    return w.replace('\\', '').replace('{', '(').replace('}', ')')


def build_ass(cap_id, timeline):
    """timeline: lista de (inicio, duracao_fala, texto) por cena."""
    st = CAPTION.get(cap_id, CAPTION_STYLES[0])
    back = _ass_color('#000000', 0x60)
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {OUT_W}
PlayResY: {OUT_H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{st['font']},{st['size']},{_ass_color(st['color'])},&H000000FF,{_ass_color(st['outline_color'])},{back},{-1 if st['bold'] else 0},{-1 if st['italic'] else 0},0,0,100,100,1,0,1,{st['outline']},{st['shadow']},2,70,70,560,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    hl = st.get('hl')
    for start, speech, text in timeline:
        words = [w for w in re.split(r'\s+', text.strip()) if w]
        if not words:
            continue
        if st['case'] == 'upper':
            words = [w.upper() for w in words]
        elif st['case'] == 'lower':
            words = [w.lower() for w in words]
        weights = [len(w) + 2 for w in words]
        total = float(sum(weights))
        span = max(0.3, speech * 0.97)
        t = start + 0.02
        times = []
        for wgt in weights:
            d = span * wgt / total
            times.append((t, t + d))
            t += d
        g = st['group']
        for gi in range(0, len(words), g):
            gw = words[gi:gi + g]
            gt = times[gi:gi + g]
            sep = ['\\N' if (st.get('stack') and len(gw) > 1 and k == (len(gw) + 1) // 2 - 1) else ' ' for k in range(len(gw))]
            pop = '{\\fscx112\\fscy112\\t(0,90,\\fscx100\\fscy100)}'
            if hl:
                for k, (ws, we) in enumerate(gt):
                    parts = []
                    for j, w in enumerate(gw):
                        w2 = _ass_text(w)
                        if j == k:
                            if hl['mode'] == 'box':
                                w2 = '{\\3c' + _ass_color(hl['color']) + '&\\bord18\\shad0}' + w2 + '{\\r}'
                            else:
                                w2 = '{\\c' + _ass_color(hl['color']) + '&}' + w2 + '{\\r}'
                        parts.append(w2 + (sep[j] if j < len(gw) - 1 else ''))
                    txt = (pop if k == 0 else '') + ''.join(parts)
                    lines.append(f'Dialogue: 0,{_ass_time(ws)},{_ass_time(we)},Cap,,0,0,0,,{txt}')
            else:
                txt = pop + ''.join(_ass_text(w) + (sep[j] if j < len(gw) - 1 else '') for j, w in enumerate(gw))
                lines.append(f'Dialogue: 0,{_ass_time(gt[0][0])},{_ass_time(gt[-1][1])},Cap,,0,0,0,,{txt}')
    return head + '\n'.join(lines) + '\n'

# --------------------------------------------------------------------------- FFmpeg

def ffmpeg(args, cwd, label):
    cmd = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y'] + args
    r = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, encoding='utf-8', errors='replace')
    if r.returncode != 0:
        raise RuntimeError(f'FFmpeg falhou ({label}): ' + (r.stderr or '')[-700:])


MOVES = ['in', 'left', 'out', 'up', 'right', 'down']


def _image_motion(move, frames, strong=False):
    """Expressões do zoompan para dar sensação de movimento a uma imagem parada (com suavização)."""
    F = max(frames - 1, 1)
    e = f"((on/{F})*(on/{F})*(3-2*(on/{F})))"          # smoothstep: começa e termina suave
    cx, cy = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    if strong:
        return f"1+0.24*{e}", cx, cy
    if move == 'in':
        return f"1+0.13*{e}", cx, cy
    if move == 'out':
        return f"1.13-0.13*{e}", cx, cy
    if move == 'left':
        return "1.16", f"(iw-iw/zoom)*{e}", cy
    if move == 'right':
        return "1.16", f"(iw-iw/zoom)*(1-{e})", cy
    if move == 'up':
        return "1.16", cx, f"(ih-ih/zoom)*(1-{e})"
    return "1.16", cx, f"(ih-ih/zoom)*{e}"          # down


def render_segment(work, i, visual, frames, move='in', strong=False):
    """Gera seg_XX.mp4 só com vídeo (1080x1920, 25 fps) com exatamente `frames` quadros."""
    out = f'seg_{i:02d}.mp4'
    seg_dur = frames / FPS
    # tremida de câmera na mão, bem sutil, para a imagem não parecer parada
    shake = (f"crop=w=iw-24:h=ih-24:x='12+5*sin(2*PI*t*0.37+{i})+2.5*sin(2*PI*t*1.13)'"
             f":y='12+5*cos(2*PI*t*0.29+{i})+2.5*sin(2*PI*t*0.87)',scale={OUT_W}:{OUT_H}")
    if visual.endswith('.png'):
        z, x, y = _image_motion(move, frames, strong)
        vf = (f"[0:v]scale=-2:2880,crop=1620:2880,zoompan=z='{z}':x='{x}':y='{y}'"
              f":d={frames}:s={OUT_W}x{OUT_H}:fps={FPS},{shake},setsar=1,format=yuv420p[v]")
        vin = ['-i', visual]
    else:
        clip = ffprobe_duration(work / visual) or 4.8
        slow = min(1.35, seg_dur / clip) if seg_dur > clip else 1.0
        vf = (f"[0:v]setpts={slow:.4f}*PTS,fps={FPS},scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,"
              f"crop={OUT_W}:{OUT_H},tpad=stop_mode=clone:stop_duration={seg_dur:.3f},trim=duration={seg_dur:.3f},"
              f"setpts=PTS-STARTPTS,setsar=1,format=yuv420p[v]")
        vin = ['-an', '-i', visual]
    ffmpeg(vin + ['-filter_complex', vf, '-map', '[v]', '-frames:v', str(frames), '-r', str(FPS), '-an',
                  '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '19', out], work, f'cena {i}')
    return out


def render_final(work, segs, timeline, cfg, music_file, total):
    (work / 'concat.txt').write_text(''.join(f"file '{s}'\n" for s in segs), encoding='utf-8')
    ffmpeg(['-f', 'concat', '-safe', '0', '-i', 'concat.txt', '-c', 'copy', 'body.mp4'], work, 'concatenação')
    (work / 'captions.ass').write_text(build_ass(cfg['caption_style'], timeline), encoding='utf-8')
    fx = cfg.get('effects', {})
    filters = []
    if fx.get('glitch'):
        on = "lt(mod(t\\,3.1)\\,0.16)"
        filters.append(f"rgbashift=rh=-10:bh=10:gv=4:enable='{on}'")
        filters.append(f"crop=w=iw-28:h=ih-28:x='14+14*sin(t*90)*{on}':y='14+14*cos(t*77)*{on}'")
        filters.append(f'scale={OUT_W}:{OUT_H}')
        filters.append(f"noise=alls=18:allf=t:enable='{on}'")
    filters.append('ass=captions.ass')
    vf = '[0:v]' + ','.join(filters) + '[v]'
    args = ['-i', 'body.mp4', '-i', 'narration.wav']
    voice = '[1:a]aresample=44100,aformat=channel_layouts=stereo,apad'
    if music_file:
        vol = float(cfg.get('music_volume') or SETTINGS.get('music_volume', 0.12))
        args += ['-i', str(music_file)]
        # a música abaixa sozinha quando há fala (sidechain) e sobe um pouco nas pausas
        af = (f'{voice},asplit=2[vo][sc];'
              f'[2:a]aresample=44100,aformat=channel_layouts=stereo,volume={vol:.3f},afade=t=in:d=1.2,'
              f'afade=t=out:st={max(0, total - 2):.2f}:d=2[m0];'
              '[m0][sc]sidechaincompress=threshold=0.02:ratio=6:attack=25:release=500[m];'
              '[vo][m]amix=inputs=2:duration=first:dropout_transition=0,volume=2[a]')
    else:
        af = f'{voice}[a]'
    args += ['-filter_complex', vf + ';' + af, '-map', '[v]', '-map', '[a]', '-t', f'{total:.3f}',
             '-c:v', 'libx264', '-preset', 'medium', '-crf', '20', '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
             '-c:a', 'aac', '-b:a', '192k', 'final.mp4']
    ffmpeg(args, work, 'montagem final')

# --------------------------------------------------------------------------- narração única

def kie_request(path, data=None, timeout=90):
    key = (SETTINGS.get('kie_key') or SETTINGS.get('compat_key') or '').strip()
    if not key:
        raise RuntimeError('Configure a chave da API do Kie AI em Configurações › Provedores de IA')
    return external(KIE_URL, path, data, timeout=timeout,
                    headers={'Authorization': 'Bearer ' + key}, auth=False)


def kie_upload_image(image_path):
    """Upload privado ao Kie para obter a URL exigida pelo endpoint Wan I2V."""
    key = (SETTINGS.get('kie_key') or SETTINGS.get('compat_key') or '').strip()
    if not key:
        raise RuntimeError('Configure a chave da API do Kie AI em Configurações › Provedores de IA')
    path = Path(image_path)
    payload = path.read_bytes()
    boundary = '----HistoriasStudio' + uuid.uuid4().hex
    filename = 'historias-studio-' + uuid.uuid4().hex + path.suffix.lower()
    mime = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
    fields = [('uploadPath', 'historias-studio/motion'), ('fileName', filename)]
    chunks = []
    for name, value in fields:
        chunks.extend([f'--{boundary}\r\n'.encode(),
                       f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                       value.encode(), b'\r\n'])
    chunks.extend([f'--{boundary}\r\n'.encode(),
                   f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode(),
                   f'Content-Type: {mime}\r\n\r\n'.encode(), payload, b'\r\n',
                   f'--{boundary}--\r\n'.encode()])
    result = external(KIE_UPLOAD_URL, '/api/file-stream-upload', timeout=120,
                      headers={'Authorization': 'Bearer ' + key,
                               'Content-Type': f'multipart/form-data; boundary={boundary}'},
                      body=b''.join(chunks), auth=False)
    if not isinstance(result, dict) or result.get('success') is False or result.get('code') not in (None, 200):
        message = result.get('msg') or result.get('message') or 'falha no upload da imagem' if isinstance(result, dict) else 'resposta inválida no upload da imagem'
        raise RuntimeError('Kie AI: ' + str(message))
    data = result.get('data') or {}
    url = data.get('downloadUrl') or data.get('download_url') or data.get('url')
    if not url:
        raise RuntimeError('Kie AI não retornou a URL pública da imagem enviada')
    return url


def kie_tts(text, voice, speed=1.0):
    model = (SETTINGS.get('kie_model') or 'google/gemini-3-8-flash-tts').strip()
    voice_name = voice if voice in KIE_VOICES else 'Kore'
    result = kie_task(model, {
        'temperature': 1,
        'speakers': [{'speaker_id': 'Narrator', 'voice_name': voice_name}],
        'dialogue_turns': [{'speaker_id': 'Narrator',
                            'style': f'Speak naturally at {max(0.5, min(2.0, float(speed or 1.0))):.2f}x speed.',
                            'text': text}],
    })
    urls = result.get('resultUrls') or result.get('result_urls') or result.get('audio_urls') or []
    url = (urls[0] if isinstance(urls, list) and urls else urls) or result.get('audioUrl') or result.get('audio_url') or result.get('url')
    if not url:
        raise RuntimeError('Kie AI concluiu a tarefa sem devolver URL do áudio')
    with urllib.request.urlopen(url, timeout=120) as response:
        return response.read()


def tts(text, voice, speed=1.0, provider=None):
    """Gera fala no provedor de voz e devolve os bytes de um WAV/MP3 já validado."""
    provider = provider or SETTINGS.get('voice_provider') or 'voicestudio'
    if provider == 'kie':
        return kie_tts(text, voice, speed)
    if provider == 'elevenlabs':
        key = _need('eleven_key', 'a chave da ElevenLabs')
        body = {'text': text, 'model_id': SETTINGS.get('eleven_model') or 'eleven_multilingual_v2'}
        if abs(float(speed) - 1.0) > 0.01:
            body['voice_settings'] = {'speed': max(0.7, min(1.2, float(speed)))}
        pcm, _ = external(ELEVEN_URL, f'/v1/text-to-speech/{urllib.parse.quote(voice)}?output_format=pcm_24000',
                          body, timeout=900, raw=True, headers={'xi-api-key': key, 'Accept': 'audio/*'}, auth=False)
        if len(pcm) < 2000 or pcm[:1] in (b'{', b'<'):
            raise RuntimeError('A ElevenLabs não retornou áudio: ' + pcm[:300].decode('utf-8', 'replace'))
        buf = io.BytesIO()
        with wave.open(buf, 'wb') as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(24000)
            w.writeframes(pcm[:len(pcm) - len(pcm) % 2])
        return buf.getvalue()
    blob, _ = external(VOICE, '/v1/audio/speech', {
        'model': SETTINGS.get('tts_model') or 'tts-1', 'voice': voice or 'default',
        'input': text, 'response_format': 'wav', 'speed': float(speed or 1.0)}, timeout=1800, raw=True)
    return blob


def detect_silences(path, noise_db=-35, min_dur=0.18):
    r = subprocess.run(['ffmpeg', '-hide_banner', '-nostats', '-i', str(path), '-af',
                        f'silencedetect=noise={noise_db}dB:d={min_dur}', '-f', 'null', '-'],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    out, start = [], None
    for line in r.stderr.splitlines():
        m = re.search(r'silence_start: (-?[\d.]+)', line)
        if m:
            start = max(0.0, float(m.group(1)))
        m = re.search(r'silence_end: ([\d.]+)', line)
        if m and start is not None:
            out.append((start, float(m.group(1))))
            start = None
    if start is not None:
        out.append((start, ffprobe_duration(path) or start))
    return out


def _split_group(texts, dur, silences):
    """Acha onde cada cena começa dentro de um áudio contínuo, usando as pausas entre parágrafos."""
    w = [len(t) + 1 for t in texts]
    tot = float(sum(w))
    lead = next((e for s, e in silences if s <= 0.05), 0.0)
    tail = next((s for s, e in silences if e >= dur - 0.05 and s > lead), dur)
    inner = [(s, e) for s, e in silences if s > 0.05 and e < dur - 0.05]
    span0, span = lead, max(0.5, tail - lead)
    scenes = [{'start': 0.0, 'speech_start': lead}]
    cum, prev = 0.0, lead
    for k in range(len(texts) - 1):
        cum += w[k]
        exp = span0 + span * cum / tot
        cands = [se for se in inner if (se[0] + se[1]) / 2 > prev + 0.4]
        best = None
        if cands:
            best = min(cands, key=lambda se: abs((se[0] + se[1]) / 2 - exp) - 0.8 * min(se[1] - se[0], 0.8))
            if abs((best[0] + best[1]) / 2 - exp) > max(1.5, 0.45 * span * w[k] / tot):
                best = None
        if best:
            cut, s_end, s_start = (best[0] + best[1]) / 2, best[0], best[1]
        else:
            cut = s_end = s_start = exp
        scenes[-1]['speech_end'] = s_end
        scenes[-1]['end'] = cut
        scenes.append({'start': cut, 'speech_start': s_start})
        prev = cut
    scenes[-1]['speech_end'] = tail
    scenes[-1]['end'] = dur
    return scenes


def narrate(work, scenes, cfg, cancelled):
    """Grava a narração do episódio inteiro numa voz só e descobre o tempo de cada cena."""
    texts = [re.sub(r'\s+', ' ', s['narration']).strip() for s in scenes]
    groups, cur, size = [], [], 0
    for i, t in enumerate(texts):
        if cur and size + len(t) > 3500:
            groups.append(cur)
            cur, size = [], 0
        cur.append(i)
        size += len(t) + 2
    groups.append(cur)
    timing, offset, parts = [], 0.0, []
    for k, g in enumerate(groups, 1):
        if cancelled():
            raise InterruptedError('cancelado')
        text = '\n\n'.join(texts[i] for i in g)
        blob = tts(text, cfg.get('voice') or 'default', float(cfg.get('speed') or 1.0),
                   cfg.get('voice_provider') or 'voicestudio')
        ext, _ = audio_valid(blob)
        raw = f'narration_part{k:02d}{ext}'
        (work / raw).write_bytes(blob)
        part = f'narration_part{k:02d}_44k.wav'
        ffmpeg(['-i', raw, '-ar', '44100', '-ac', '1', '-c:a', 'pcm_s16le', part], work, 'narração')
        dur = ffprobe_duration(work / part) or 0
        if dur <= 0:
            raise RuntimeError('A narração veio vazia do VoiceStudio')
        for sc in _split_group([texts[i] for i in g], dur, detect_silences(work / part)):
            timing.append({key: round(val + offset, 3) for key, val in sc.items()})
        offset += dur
        parts.append(part)
    if len(parts) == 1:
        shutil.copy(work / parts[0], work / 'narration.wav')
    else:
        ins = sum((['-i', p] for p in parts), [])
        ffmpeg(ins + ['-filter_complex', ''.join(f'[{i}:a]' for i in range(len(parts))) +
                      f'concat=n={len(parts)}:v=0:a=1[a]', '-map', '[a]', '-c:a', 'pcm_s16le', 'narration.wav'],
               work, 'narração')
    return {'file': 'narration.wav', 'duration': round(offset, 3), 'scenes': timing}


def scene_frames(timing):
    """Quadros de cada cena calculados a partir dos cortes acumulados (sem erro de arredondamento)."""
    cuts = [s['start'] for s in timing['scenes']] + [timing['duration'] + 0.8]
    marks = [int(round(c * FPS)) for c in cuts]
    return [max(1, marks[k + 1] - marks[k]) for k in range(len(timing['scenes']))]

# --------------------------------------------------------------------------- fila de vídeos

QUEUE = []
CANCEL = set()
PAUSE = set()
STEPS = {'queued': 'Na fila', 'script': 'Escrevendo roteiro', 'voice': 'Gravando narração', 'music': 'Compondo trilha',
         'images': 'Gerando imagens', 'motion': 'Animando cenas', 'render': 'Montando vídeo',
         'done': 'Pronto', 'error': 'Erro', 'cancelled': 'Cancelado', 'paused': 'Pausado para edição'}


def _upd(v, **kw):
    with LOCK:
        v.update(kw)
        v['updated'] = now_str()
        if 'status' in kw:
            v['step_label'] = STEPS.get(kw['status'], kw['status'])
            if kw['status'] in ('script', 'voice', 'images', 'motion', 'music', 'render'):
                v['stage'] = kw['status']
    save_videos()


def series_config(s):
    keys = ('name', 'niche', 'example', 'story_mode', 'language', 'voice', 'voice_name', 'voice_provider', 'speed', 'music', 'music_volume',
            'art_style', 'caption_style', 'effects', 'platforms', 'duration', 'music_mode')
    return {k: json.loads(json.dumps(s.get(k))) for k in keys}


def enqueue_video(series_id, publish_at=None, reason='manual', config_override=None):
    s = SERIES.get(series_id)
    if not s:
        raise ValueError('Série não encontrada')
    vid = uuid.uuid4().hex[:12]
    v = {'id': vid, 'series_id': series_id, 'series_name': s['name'], 'status': 'queued', 'step_label': 'Na fila',
         'progress': 0, 'created': now_str(), 'updated': now_str(), 'title': '', 'description': '', 'hashtags': [],
         'script': None, 'error': None, 'file': None, 'thumb': None, 'duration': None, 'publish_at': publish_at,
         'reason': reason, 'config': dict(series_config(s), **(config_override or {})),
         'seed': random.randint(1, 2 ** 31 - 1), 'export_path': None}
    with LOCK:
        VIDEOS[vid] = v
        QUEUE.append(vid)
    save_videos()
    return v


def retry_video(vid):
    v = VIDEOS.get(vid)
    if not v:
        raise ValueError('Vídeo não encontrado')
    if v['status'] not in ('error', 'cancelled', 'done', 'paused'):
        raise ValueError('Este vídeo já está em produção')
    CANCEL.discard(vid)
    PAUSE.discard(vid)
    _upd(v, status='queued', error=None, progress=0, pause_requested=False)
    with LOCK:
        QUEUE.append(vid)
    return v


def cancel_video(vid):
    v = VIDEOS.get(vid)
    if not v:
        raise ValueError('Vídeo não encontrado')
    with LOCK:
        PAUSE.discard(vid)
        if vid in QUEUE:
            QUEUE.remove(vid)
            _upd(v, status='cancelled')
        elif v['status'] not in ('done', 'error', 'cancelled'):
            CANCEL.add(vid)
    return v


def pause_video(vid):
    v = VIDEOS.get(vid)
    if not v:
        raise ValueError('Vídeo não encontrado')
    with LOCK:
        if v['status'] in ('done', 'error', 'cancelled', 'paused'):
            raise ValueError('Este vídeo não está em produção')
        if vid in QUEUE:
            QUEUE.remove(vid)
            _upd(v, status='paused', pause_requested=False)
        else:
            PAUSE.add(vid)
            CANCEL.add(vid)
            _upd(v, pause_requested=True)
    return v


def delete_video(vid):
    cancel_video(vid)
    with LOCK:
        VIDEOS.pop(vid, None)
    save_videos()
    shutil.rmtree(VIDEOS_DIR / vid, ignore_errors=True)


def generate_score(v, cfg, script, total, work, cancelled):
    raise RuntimeError('Trilha automática indisponível (score.py não carregado)')   # substituída por score.py


def motion_mode(fx):
    m = (fx or {}).get('motion')
    if m in ('image', 'video'):
        return m
    return 'video' if SETTINGS.get('animate_all_scenes') else 'image'   # séries antigas


def _safe(name, n=80):
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', name).strip().strip('.')
    return (s or 'video')[:n]


def produce(v):
    vid = v['id']
    cfg = v['config']
    work = VIDEOS_DIR / vid
    work.mkdir(parents=True, exist_ok=True)
    cancelled = lambda: vid in CANCEL

    def check():
        if cancelled():
            raise InterruptedError('cancelado')

    # 1. roteiro
    if not v.get('script'):
        _upd(v, status='script', progress=3)
        prev = [x['title'] for x in VIDEOS.values() if x['series_id'] == v['series_id'] and x.get('title')]
        series = SERIES.get(v['series_id'])
        script = write_script(cfg, prev, series)
        if series and series.get('story_mode') == 'continuous':
            with LOCK:                          # novos personagens entram no elenco fixo da série
                known = {c['name'].lower() for c in series.setdefault('cast', [])}
                for c in script['characters']:
                    if c['name'].lower() not in known and len(series['cast']) < 12:
                        series['cast'].append({'name': c['name'], 'look': c['look']})
            save_series()
        _upd(v, script=script, title=script['title'], description=script['description'], hashtags=script['hashtags'])
    script = v['script']
    scenes = script['scenes']
    n = len(scenes)
    check()

    # 2. narração (uma voz só para o episódio inteiro)
    if not (script.get('timing') and (work / 'narration.wav').is_file()):
        _upd(v, status='voice', progress=10)
        script['timing'] = narrate(work, scenes, cfg, cancelled)
        _upd(v, script=script, progress=25)
    timing = script['timing']
    frames = scene_frames(timing)

    # 3. imagens (+ fichas de personagem como referência, nos provedores em nuvem)
    _upd(v, status='images', progress=25)
    st = get_style(cfg['art_style'])
    negative = NEG_BASE + ', ' + st['negative']
    prov = SETTINGS.get('image_provider') or 'comfyui'
    sheets = {}
    if supports_refs(prov):
        series = SERIES.get(v['series_id']) or {}
        folder = (CAST_DIR / v['series_id']) if series.get('story_mode') == 'continuous' else (work / 'elenco')
        main = [c for c in script.get('characters', []) if any(c in scene_characters(script, s) for s in scenes)][:4]
        for c in main:
            check()
            sheets[c['name']] = ensure_sheet(c, cfg, folder, v['seed'], cancelled)
    todo = [i for i in range(1, n + 1) if not (work / f'scene_{i:02d}.png').is_file()]
    done_count = [n - len(todo)]

    def one(i):
        if cancelled():
            raise InterruptedError('cancelado')
        sc = scenes[i - 1]
        chars = [c['name'] for c in scene_characters(script, sc) if c['name'] in sheets][:5]
        blob = make_image(build_image_prompt(cfg, script, sc), negative, v['seed'], f'HistoriasStudio/{vid}_cena_{i:02d}',
                          refs=[sheets[c] for c in chars], ref_names=chars, cancelled=cancelled, provider=prov)
        (work / f'scene_{i:02d}.png').write_bytes(blob)
        with LOCK:
            done_count[0] += 1
        if i == 1:
            _upd(v, thumb='scene_01.png')
        _upd(v, progress=25 + int(25 * done_count[0] / n))

    workers = max(1, int(SETTINGS.get('image_parallel') or 3)) if supports_refs(prov) else 1
    if workers == 1:
        for i in todo:
            one(i)
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            for f in [pool.submit(one, i) for i in todo]:
                f.result()
    if not v.get('thumb'):
        _upd(v, thumb='scene_01.png')

    # 4. movimento por vídeo (LTX-2): todas as cenas no modo "vídeo", ou só a 1ª com o gancho animado
    fx = cfg.get('effects') or {}
    mode = motion_mode(fx)
    animate = [i for i in range(1, n + 1) if mode == 'video' or (fx.get('hook') and i == 1)]
    motion_provider = SETTINGS.get('motion_provider') or 'comfyui'
    if animate and (motion_provider in ('kie', 'fal', 'replicate') or VID_WF is not None):
        _upd(v, status='motion', progress=50)
        for k, i in enumerate(animate, 1):
            check()
            if list(work.glob(f'motion_{i:02d}.*')):
                continue
            sc = scenes[i - 1]
            if motion_provider == 'kie':
                blob, ext = animate_image_kie(work / f'scene_{i:02d}.png', build_motion_prompt(cfg, script, sc),
                                              v['seed'] + i, cancelled)
            elif motion_provider == 'fal':
                blob, ext = fal_animate_image(work / f'scene_{i:02d}.png', build_motion_prompt(cfg, script, sc),
                                              v['seed'] + i, frames[i - 1], cancelled)
            elif motion_provider == 'replicate':
                blob, ext = replicate_animate_image(work / f'scene_{i:02d}.png', build_motion_prompt(cfg, script, sc),
                                                    v['seed'] + i, frames[i - 1], cancelled)
            else:
                blob, ext = animate_image(work / f'scene_{i:02d}.png', build_motion_prompt(cfg, script, sc),
                                          v['seed'] + i, ltx_frames(frames[i - 1] / FPS),
                                          f'HistoriasStudio/video/{vid}_cena_{i:02d}', cancelled)
            (work / f'motion_{i:02d}{ext}').write_bytes(blob)
            _upd(v, progress=50 + int(35 * k / len(animate)))

    # 5. trilha sonora composta pela IA a partir do roteiro (ACE-Step), com a duração exata do vídeo
    total = sum(frames) / FPS
    score = None
    if cfg.get('music_mode') == 'ai':
        check()
        try:
            score = generate_score(v, cfg, script, total + 0.5, work, cancelled)
            _upd(v, music_warning=None)
        except InterruptedError:
            raise
        except Exception as exc:
            _upd(v, music_warning='Não foi possível compor a trilha com IA (' + str(exc)[:300] + '). '
                                  + ('Usei uma música da biblioteca.' if cfg.get('music') else 'O vídeo saiu sem música.'))

    # 6. montagem: cenas cortadas no tempo exato da narração, trilha de voz contínua
    check()
    _upd(v, status='render', progress=88)
    segs, timeline = [], []
    rnd = random.Random(v['seed'])
    moves = MOVES[:]
    rnd.shuffle(moves)
    for i, sc in enumerate(scenes, 1):
        check()
        motion = sorted(work.glob(f'motion_{i:02d}.*'))
        visual = motion[0].name if motion else f'scene_{i:02d}.png'
        strong = (i == 1 and fx.get('hook') and not motion)
        segs.append(render_segment(work, i, visual, frames[i - 1], moves[(i - 1) % len(moves)], strong))
        tm = timing['scenes'][i - 1]
        timeline.append((tm['speech_start'], max(0.3, tm['speech_end'] - tm['speech_start']), sc['narration']))
        _upd(v, progress=88 + int(8 * i / n))
    t = sum(frames) / FPS
    music = score
    tracks = [] if music else [m for m in (cfg.get('music') or []) if (MUSIC_DIR / m).is_file()]
    if tracks:
        music = MUSIC_DIR / random.choice(tracks)
    if music:
        music = music_bed(music, t + 0.5, work)       # repete com emenda suave se a música for curta
    render_final(work, segs, timeline, cfg, music, t)

    # exporta cópia amigável
    folder = EXPORT_DIR / _safe(cfg['name'])
    folder.mkdir(parents=True, exist_ok=True)
    base = f"{datetime.date.today().isoformat()} - {_safe(v['title'], 70)}"
    dest = folder / (base + '.mp4')
    k = 2
    while dest.exists():
        dest = folder / f'{base} ({k}).mp4'
        k += 1
    shutil.copy(work / 'final.mp4', dest)
    dest.with_suffix('.txt').write_text(
        f"{v['title']}\n\n{v['description']}\n\n{' '.join(v['hashtags'])}\n", encoding='utf-8')
    if not SETTINGS.get('keep_work_files', True):
        for p in work.glob('seg_*.mp4'):
            p.unlink()
        (work / 'body.mp4').unlink(missing_ok=True)
    _upd(v, status='done', progress=100, file='final.mp4', duration=round(t, 1), export_path=str(dest))
    series = SERIES.get(v['series_id'])
    if series is not None and not any(e.get('video') == vid for e in series.get('episodes', [])):
        with LOCK:
            series.setdefault('episodes', []).append({'video': vid, 'title': v['title'],
                                                      'summary': script.get('summary') or v.get('description', '')})
        save_series()


def worker():
    while True:
        with LOCK:
            vid = QUEUE.pop(0) if QUEUE else None
        if not vid:
            time.sleep(1)
            continue
        v = VIDEOS.get(vid)
        if not v:
            continue
        try:
            produce(v)
        except InterruptedError:
            _upd(v, status='paused' if vid in PAUSE else 'cancelled', pause_requested=False)
        except Exception as exc:
            _upd(v, status='error', error=str(exc)[:1500])
        finally:
            CANCEL.discard(vid)
            PAUSE.discard(vid)
            if v.get('pause_requested'):
                _upd(v, pause_requested=False)

# --------------------------------------------------------------------------- agenda diária

def _gen_time(s):
    hh, mm = map(int, s.get('publish_time', '19:00').split(':'))
    lead = float(SETTINGS.get('lead_hours', 6))
    pub = datetime.datetime.combine(datetime.date.today(), datetime.time(hh, mm))
    gen_at = pub - datetime.timedelta(hours=lead)
    # se a geração cairia no dia anterior, hoje gera para a publicação de amanhã
    if gen_at.date() < pub.date():
        gen_at += datetime.timedelta(days=1)
        pub += datetime.timedelta(days=1)
    return gen_at, pub


def scheduler():
    while True:
        try:
            today = datetime.date.today().isoformat()
            for sid, s in list(SERIES.items()):
                if not s.get('active'):
                    continue
                gen_at, pub = _gen_time(s)
                if datetime.datetime.now() >= gen_at and s.get('last_scheduled') != today:
                    s['last_scheduled'] = today
                    save_series()
                    enqueue_video(sid, publish_at=pub.strftime('%Y-%m-%d %H:%M'), reason='agenda')
        except Exception as exc:
            print('Agenda:', exc, flush=True)
        time.sleep(30)


def start():
    # retoma vídeos interrompidos (o pipeline reaproveita o que já existe em disco)
    for v in VIDEOS.values():
        if v.get('pause_requested'):
            v.update(status='paused', step_label=STEPS['paused'], pause_requested=False)
    pending = sorted((v for v in VIDEOS.values() if v['status'] not in ('done', 'error', 'cancelled', 'paused')),
                     key=lambda v: v['created'])
    for v in pending:
        v['status'] = 'queued'
        v['step_label'] = 'Na fila (retomado)'
        QUEUE.append(v['id'])
    save_videos()
    threading.Thread(target=worker, daemon=True).start()
    threading.Thread(target=scheduler, daemon=True).start()

# --------------------------------------------------------------------------- séries

def validate_series(d, partial=False):
    out = {}
    def has(k):
        return k in d
    if not partial or has('name'):
        name = str(d.get('name', '')).strip()
        if not name:
            raise ValueError('Dê um nome para a série')
        out['name'] = name[:120]
    if not partial or has('niche'):
        niche = str(d.get('niche', '')).strip()
        if len(niche) < 10:
            raise ValueError('Descreva o nicho com pelo menos 10 caracteres')
        out['niche'] = niche[:5000]
        out['niche_preset'] = str(d.get('niche_preset') or '')[:60]
    if not partial or has('example'):
        out['example'] = str(d.get('example') or '')[:2000]
    if not partial or has('language'):
        out['language'] = d.get('language') if d.get('language') in LANG else 'pt-BR'
    if not partial or has('voice'):
        out['voice'] = str(d.get('voice') or 'default')[:200]
        out['voice_name'] = str(d.get('voice_name') or out['voice'])[:200]
        vp = d.get('voice_provider')
        out['voice_provider'] = vp if vp in VOICE_PROVIDERS else SETTINGS.get('voice_provider', 'voicestudio')
    if not partial or has('speed'):
        sp = float(d.get('speed') or 1.0)
        out['speed'] = min(2.0, max(0.5, sp))
    if not partial or has('music_mode'):
        out['music_mode'] = 'ai' if d.get('music_mode') == 'ai' else 'library'
    if not partial or has('music'):
        out['music'] = [str(m) for m in (d.get('music') or []) if isinstance(m, str)][:50]
    if not partial or has('music_volume'):
        out['music_volume'] = min(0.6, max(0.0, float(d.get('music_volume') if d.get('music_volume') is not None else SETTINGS['music_volume'])))
    if not partial or has('art_style'):
        out['art_style'] = d.get('art_style') if d.get('art_style') in styles_map() else STYLES_LIST[0]['id']
    if not partial or has('caption_style'):
        out['caption_style'] = d.get('caption_style') if d.get('caption_style') in CAPTION else 'red_highlight'
    if not partial or has('effects'):
        e = d.get('effects') or {}
        out['effects'] = {'glitch': bool(e.get('glitch')), 'hook': bool(e.get('hook')),
                          'motion': e.get('motion') if e.get('motion') in ('image', 'video') else 'image'}
    if not partial or has('platforms'):
        ids = {p['id'] for p in PLATFORMS}
        out['platforms'] = [p for p in (d.get('platforms') or []) if p in ids]
    if not partial or has('duration'):
        out['duration'] = d.get('duration') if d.get('duration') in DUR else '30-40'
    if not partial or has('story_mode'):
        out['story_mode'] = 'continuous' if d.get('story_mode') == 'continuous' else 'independent'
    if not partial or has('publish_time'):
        pt = str(d.get('publish_time') or '19:00')
        if not re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d', pt):
            raise ValueError('Horário inválido')
        out['publish_time'] = pt
    if has('active'):
        out['active'] = bool(d.get('active'))
    return out


def create_series(d):
    data = validate_series(d)
    sid = uuid.uuid4().hex[:10]
    s = dict(data, id=sid, created=now_str(), active=bool(d.get('active', True)), last_scheduled=None)
    gen_at, _ = _gen_time(s)
    if datetime.datetime.now() >= gen_at:
        s['last_scheduled'] = datetime.date.today().isoformat()
    with LOCK:
        SERIES[sid] = s
    save_series()
    out = dict(s)
    if d.get('generate_now', True):
        out['first_video'] = enqueue_video(sid, reason='primeiro vídeo')['id']
    return out


def series_summary(s):
    vids = [v for v in VIDEOS.values() if v['series_id'] == s['id']]
    gen_at, pub = _gen_time(s)
    return dict(s, video_count=len(vids), done_count=sum(1 for v in vids if v['status'] == 'done'),
                producing=sum(1 for v in vids if v['status'] not in ('done', 'error', 'cancelled', 'paused')),
                generate_time=gen_at.strftime('%H:%M'),
                cast=[dict(c, sheet=next((f"/media/cast/{s['id']}/{p.name}" for p in sorted((CAST_DIR / s['id']).glob(_char_slug(c['name']) + '__*.png'))), None))
                      for c in s.get('cast', [])],
                episodes_count=len(s.get('episodes', [])),
                thumb=next((f"/media/videos/{v['id']}/{v['thumb']}" for v in sorted(vids, key=lambda x: x['created'], reverse=True) if v.get('thumb')), None))

# --------------------------------------------------------------------------- prévias

STYLE_JOBS = {}


def style_preview(style_id):
    st = styles_map().get(style_id)
    if not st:
        raise ValueError('Estilo inválido')
    if STYLE_JOBS.get(style_id) == 'running':
        return
    STYLE_JOBS[style_id] = 'running'

    def job():
        try:
            subject = st.get('preview_prompt', '').strip() or (
                'a Brazilian family of three laughing together in a cozy kitchen, mother holding a coffee cup, '
                'father telling a joke, teenage daughter rolling her eyes')
            prompt = f"{st['prompt']}, {subject}, vertical 9:16 composition, no text"
            blob = make_image(prompt, NEG_BASE + ', ' + st.get('negative', ''), random.randint(1, 99999),
                              f'HistoriasStudio/estilos/{style_id}')
            (STYLE_PREV / f'{style_id}.png').write_bytes(blob)
            STYLE_JOBS[style_id] = 'done'
        except Exception as exc:
            STYLE_JOBS[style_id] = 'erro: ' + str(exc)[:200]
    threading.Thread(target=job, daemon=True).start()


def voice_preview(voice, lang_id, provider=None):
    lang = LANG.get(lang_id, LANGUAGES[0])
    provider = provider if provider in VOICE_PROVIDERS else SETTINGS.get('voice_provider', 'voicestudio')
    key = provider + '_' + re.sub(r'[^A-Za-z0-9_-]', '_', voice)[:80] + '_' + lang['id']
    for ext in ('.wav', '.mp3'):
        p = VOICE_PREV / (key + ext)
        if p.is_file() and p.stat().st_size > 1000:
            return p
    blob = tts(lang['sample'], voice, 1.0, provider)
    ext, _ = audio_valid(blob)
    p = VOICE_PREV / (key + ext)
    p.write_bytes(blob)
    return p


KIE_VOICES = ('Zephyr', 'Puck', 'Charon', 'Kore', 'Fenrir', 'Leda', 'Orus', 'Aoede',
              'Callirrhoe', 'Autonoe', 'Enceladus', 'Iapetus', 'Umbriel', 'Algieba',
              'Despina', 'Erinome', 'Algenib', 'Rasalgethi', 'Laomedeia', 'Achernar',
              'Alnilam', 'Schedar', 'Gacrux', 'Pulcherrima', 'Achird', 'Zubenelgenubi',
              'Vindemiatrix', 'Sadachbia', 'Sadaltager', 'Sulafat')


def list_voices():
    if SETTINGS.get('voice_provider') == 'kie':
        return [{'id': v, 'name': v, 'gender': None, 'tag': None, 'language': None, 'provider': 'kie'}
                for v in KIE_VOICES]
    if SETTINGS.get('voice_provider') == 'elevenlabs':
        key = _need('eleven_key', 'a chave da ElevenLabs')
        d = external(ELEVEN_URL, '/v1/voices', timeout=20, headers={'xi-api-key': key}, auth=False)
        out = []
        for v in d.get('voices', []):
            lab = v.get('labels') or {}
            g = str(lab.get('gender') or '').lower()
            tag = lab.get('descriptive') or lab.get('use_case') or lab.get('description') or lab.get('accent') or v.get('category')
            out.append({'id': v['voice_id'], 'name': v.get('name') or v['voice_id'],
                        'gender': 'male' if g == 'male' else 'female' if g == 'female' else None,
                        'tag': str(tag).replace('_', ' ').capitalize()[:24] if tag else None, 'language': None,
                        'provider': 'elevenlabs'})
        return out
    d = external(VOICE, '/v1/audio/voices', timeout=15)
    raw = d if isinstance(d, list) else (d.get('voices') or d.get('data') or [])
    out = []
    for v in raw:
        if isinstance(v, str):
            out.append({'id': v, 'name': v, 'gender': None, 'tag': None, 'language': None})
        elif isinstance(v, dict):
            vid = v.get('voice_id') or v.get('id') or v.get('name')
            if not vid:
                continue
            g = str(v.get('gender') or (v.get('labels') or {}).get('gender') or '').lower()
            g = 'male' if g in ('male', 'masculino', 'm', 'man') else 'female' if g in ('female', 'feminino', 'f', 'woman') else None
            tag = v.get('style') or v.get('description') or (v.get('labels') or {}).get('description') or v.get('category')
            out.append({'id': str(vid), 'name': str(v.get('name') or v.get('label') or vid), 'gender': g,
                        'tag': str(tag)[:24] if tag else None,
                        'language': v.get('language') or v.get('lang') or (v.get('labels') or {}).get('language')})
    return out


MUSIC_EXTS = ('.mp3', '.wav', '.m4a', '.ogg', '.aac', '.flac')
MUSIC_META = _load('music.json', {})


def music_file(name):
    p = MUSIC_DIR / Path(urllib.parse.unquote(name)).name
    if p.suffix.lower() not in MUSIC_EXTS or not p.is_file():
        raise ValueError('Música não encontrada')
    return p


def list_music():
    out, changed = [], False
    for p in sorted(MUSIC_DIR.iterdir()):
        if p.suffix.lower() not in MUSIC_EXTS:
            continue
        m = MUSIC_META.setdefault(p.name, {})
        if m.get('size') != p.stat().st_size or not m.get('duration'):
            m['size'], m['duration'] = p.stat().st_size, round(ffprobe_duration(p) or 0, 1)
            changed = True
        name = m.get('name') or p.stem.replace('_', ' ').replace('-', ' ').strip()
        tags = m.get('tags') or []
        dur = m.get('duration') or 0
        out.append({'file': p.name, 'name': name, 'tags': tags, 'duration': dur, 'size': p.stat().st_size,
                    'desc': ' · '.join(([f'{int(dur // 60)}:{int(dur % 60):02d}'] if dur else []) + tags)})
    if changed:
        _save('music.json', MUSIC_META)
    return out


def _clean_music(src, dest):
    """Normaliza (44,1 kHz estéreo) e tira o silêncio do começo e do fim, para a emenda não ter buraco."""
    ffmpeg(['-i', str(src), '-af',
            'aresample=44100,aformat=channel_layouts=stereo,'
            'silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.05,areverse,'
            'silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.05,areverse',
            '-c:a', 'pcm_s16le', dest.name], dest.parent, 'música')
    return ffprobe_duration(dest) or 0


def _loop_chain(n, xf):
    """Filtro que encadeia n cópias com crossfade de potência constante (emenda imperceptível)."""
    if n == 1:
        return '[0:a]anull[out]'
    parts, last = [], '[0:a]'
    for k in range(1, n):
        lbl = '[out]' if k == n - 1 else f'[x{k}]'
        parts.append(f'{last}[{k}:a]acrossfade=d={xf:.2f}:c1=qsin:c2=qsin{lbl}')
        last = lbl
    return ';'.join(parts)


def music_bed(src, total, work):
    """Devolve uma trilha de música com pelo menos `total` segundos. Se a música for mais curta,
    ela é repetida e cada emenda é feita com crossfade suave, sem corte nem silêncio."""
    clean = work / 'music_clean.wav'
    d = _clean_music(src, clean)
    if d <= 1:
        return src
    if d >= total:
        return clean
    xf = max(0.8, min(3.0, d * 0.2))
    n = min(60, int(math.ceil((total - xf) / (d - xf))) + 1)
    ffmpeg(sum((['-i', clean.name] for _ in range(n)), []) + ['-filter_complex', _loop_chain(n, xf), '-map', '[out]',
           '-t', f'{total:.2f}', '-c:a', 'pcm_s16le', 'music_bed.wav'], work, 'música em loop')
    return work / 'music_bed.wav'


def music_loop_preview(name):
    """Trecho de ~12 s com a emenda no meio: final da música -> começo da música."""
    src = music_file(name)
    key = re.sub(r'[^A-Za-z0-9_-]', '_', src.stem)[:80] + f'_{src.stat().st_size}.wav'
    out = MUSIC_PREV / key
    if out.is_file():
        return out
    clean = MUSIC_PREV / ('clean_' + key)
    d = _clean_music(src, clean)
    xf = max(0.8, min(3.0, d * 0.2))
    tail = max(0.0, d - 6 - xf)
    ffmpeg(['-ss', f'{tail:.2f}', '-i', clean.name, '-t', '6', '-i', clean.name, '-filter_complex',
            f'[0:a][1:a]acrossfade=d={xf:.2f}:c1=qsin:c2=qsin,afade=t=in:d=0.4[out]', '-map', '[out]',
            '-c:a', 'pcm_s16le', out.name], MUSIC_PREV, 'prévia da emenda')
    clean.unlink(missing_ok=True)
    return out

# --------------------------------------------------------------------------- HTTP

CTYPES = {'.mp4': 'video/mp4', '.webm': 'video/webm', '.png': 'image/png', '.jpg': 'image/jpeg', '.wav': 'audio/wav',
          '.mp3': 'audio/mpeg', '.m4a': 'audio/mp4', '.ogg': 'audio/ogg', '.aac': 'audio/aac', '.flac': 'audio/flac',
          '.txt': 'text/plain; charset=utf-8', '.ass': 'text/plain; charset=utf-8'}


def serve_file(h, path, download_name=None):
    path = Path(path)
    if not path.is_file():
        h.send(404, {'error': 'Arquivo não encontrado'})
        return
    size = path.stat().st_size
    ctype = CTYPES.get(path.suffix.lower(), 'application/octet-stream')
    rng = h.headers.get('Range', '')
    m = re.fullmatch(r'bytes=(\d*)-(\d*)', rng.strip()) if rng else None
    start, end = 0, size - 1
    if m and (m.group(1) or m.group(2)):
        a, b = m.groups()
        if a:
            start = int(a)
            end = min(int(b), size - 1) if b else size - 1
        else:
            start = max(0, size - int(b))
        if start >= size or start > end:
            h.send_response(416)
            h.send_header('Content-Range', f'bytes */{size}')
            h.end_headers()
            return
    else:
        m = None
    h.send_response(206 if m else 200)
    h.send_header('Content-Type', ctype)
    h.send_header('Accept-Ranges', 'bytes')
    h.send_header('Cache-Control', 'no-cache')
    h.send_header('Content-Length', str(end - start + 1))
    if m:
        h.send_header('Content-Range', f'bytes {start}-{end}/{size}')
    if download_name:
        h.send_header('Content-Disposition', "attachment; filename*=UTF-8''" + urllib.parse.quote(download_name))
    h.end_headers()
    try:
        with path.open('rb') as f:
            f.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = f.read(min(262144, left))
                if not chunk:
                    break
                h.wfile.write(chunk)
                left -= len(chunk)
    except (BrokenPipeError, ConnectionResetError):
        pass


def style_preview_url(sid):
    p = STYLE_PREV / f'{sid}.png'
    return f"/media/styles/{sid}.png?v={int(p.stat().st_mtime)}" if p.is_file() else None


def _slug(name):
    import unicodedata
    s = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode().lower()
    s = re.sub(r'[^a-z0-9]+', '_', s).strip('_')[:40] or 'estilo'
    base, k = s, 2
    while s in styles_map():
        s = f'{base}_{k}'
        k += 1
    return s


def save_style(d):
    name = str(d.get('name', '')).strip()[:60]
    prompt = str(d.get('prompt', '')).strip()[:2000]
    if not name:
        raise ValueError('Dê um nome para o estilo')
    if len(prompt) < 5:
        raise ValueError('Escreva o prompt do estilo')
    item = {'name': name, 'prompt': prompt, 'negative': str(d.get('negative', '')).strip()[:2000],
            'motion': str(d.get('motion', '')).strip()[:1000],
            'preview_prompt': str(d.get('preview_prompt', '')).strip()[:1000]}
    with LOCK:
        cur = styles_map().get(d.get('id') or '')
        if cur:
            visual_changed = any(cur.get(k, '') != item[k] for k in ('prompt', 'negative', 'preview_prompt'))
            cur.update(item)
            st = cur
        else:
            st = dict(item, id=_slug(name))
            STYLES_LIST.append(st)
            visual_changed = True
    save_styles()
    if visual_changed:
        (STYLE_PREV / f"{st['id']}.png").unlink(missing_ok=True)
        STYLE_JOBS.pop(st['id'], None)
        try:
            style_preview(st['id'])
        except Exception:
            pass
    return st


def delete_style(sid):
    with LOCK:
        if len(STYLES_LIST) <= 1:
            raise ValueError('Mantenha pelo menos um estilo')
        STYLES_LIST[:] = [s for s in STYLES_LIST if s['id'] != sid]
    save_styles()


def move_style(sid, delta):
    with LOCK:
        ids = [s['id'] for s in STYLES_LIST]
        if sid in ids:
            i = ids.index(sid)
            j = max(0, min(len(ids) - 1, i + delta))
            STYLES_LIST.insert(j, STYLES_LIST.pop(i))
    save_styles()


def settings_public():
    d = {k: v for k, v in SETTINGS.items() if k not in SECRET_KEYS}
    for k in SECRET_KEYS:
        val = SETTINGS.get(k) or ''
        d[k + '_set'] = bool(val)
        d[k + '_hint'] = ('••••' + val[-4:]) if len(val) > 8 else ('••••' if val else '')
    return d


def test_provider(kind):
    if kind == 'script':
        txt, model = llm_chat('Responda apenas com JSON no formato {"ok": true, "mensagem": "<uma frase curta em português dizendo que está funcionando>"}',
                              0.3, timeout=120)
        try:
            msg = _extract_json(txt).get('mensagem') or txt
        except Exception:
            msg = txt
        return {'ok': True, 'detail': f'{model}: {str(msg)[:160]}'}
    if kind == 'motion':
        provider = SETTINGS.get('motion_provider', 'comfyui')
        cloud_keys = {'kie': 'kie_key', 'fal': 'fal_key', 'replicate': 'replicate_key'}
        if provider in cloud_keys:
            if not (SETTINGS.get(cloud_keys[provider]) or (provider == 'kie' and SETTINGS.get('compat_key'))):
                raise RuntimeError(f'Configure a chave do {MOTION_PROVIDERS[provider]} em Configurações › Provedores de IA')
            return {'ok': True, 'detail': f"{MOTION_PROVIDERS[provider]} configurado; consulte o custo na conta do provedor. O modelo será confirmado na primeira geração."}
        if VID_WF is None:
            raise RuntimeError('workflow_video.json não encontrado para o ComfyUI local')
        return {'ok': True, 'detail': 'ComfyUI · LTX-2: workflow encontrado'}
    if kind == 'image':
        prov = SETTINGS.get('image_provider', 'comfyui')
        blob = make_image('a friendly orange cat wearing a tiny red scarf sitting on a wooden table, cartoon illustration',
                          NEG_BASE, 7, 'HistoriasStudio/teste')
        (DATA / 'test_image.png').write_bytes(blob)
        return {'ok': True, 'detail': f'{IMAGE_PROVIDERS.get(prov, prov)}: imagem gerada',
                'image': f'/media/test_image.png?v={int(time.time())}'}
    voices = list_voices()
    return {'ok': True, 'detail': f"{VOICE_PROVIDERS.get(SETTINGS.get('voice_provider'), '')}: {len(voices)} vozes encontradas"}


def _public_config():
    prev = {}
    for st in STYLES_LIST:
        prev[st['id']] = style_preview_url(st['id'])
    return {'languages': [{k: l[k] for k in ('id', 'name', 'flag')} for l in LANGUAGES], 'durations': DURATIONS,
            'art_styles': [{'id': s['id'], 'name': s['name'], 'preview': prev[s['id']], 'job': STYLE_JOBS.get(s['id'])}
                           for s in STYLES_LIST],
            'caption_styles': [{'id': c['id'], 'name': c['name']} for c in CAPTION_STYLES],
            'platforms': PLATFORMS, 'motion_available': VID_WF is not None or SETTINGS.get('motion_provider') in ('kie', 'fal', 'replicate'), 'settings': settings_public()}


def _video_public(v):
    out = {k: v.get(k) for k in ('id', 'series_id', 'series_name', 'status', 'step_label', 'progress', 'created',
                                 'updated', 'title', 'description', 'hashtags', 'error', 'duration', 'publish_at',
                                 'reason', 'export_path', 'stage', 'music_warning', 'pause_requested')}
    out['score'] = (v.get('script') or {}).get('score')
    out['target_seconds'] = DUR.get((v.get('config') or {}).get('duration'), {}).get('seconds')
    base = f"/media/videos/{v['id']}/"
    out['thumb'] = base + v['thumb'] if v.get('thumb') else None
    out['url'] = base + v['file'] if v.get('file') else None
    out['scenes'] = [{'narration': s['narration'], 'image_prompt': s['image_prompt'],
                      'motion_prompt': s.get('motion_prompt')} for s in (v.get('script') or {}).get('scenes', [])]
    out['queue_position'] = QUEUE.index(v['id']) + 1 if v['id'] in QUEUE else None
    d = VIDEOS_DIR / v['id']
    out['images'] = [base + p.name for p in sorted(d.glob('scene_*.png'))] if d.is_dir() else []
    out['motion_done'] = len(list(d.glob('motion_*.*'))) if d.is_dir() else 0
    out['art_style'] = (v.get('config') or {}).get('art_style')
    return out


def _read_json(h, limit=2_000_000):
    n = min(int(h.headers.get('Content-Length', '0') or 0), limit)
    raw = h.rfile.read(n) if n else b'{}'
    return json.loads(raw or b'{}')


def route(h, method):
    """Rotas novas. Retorna True quando a requisição foi tratada."""
    p = urllib.parse.urlparse(h.path)
    path = p.path
    q = urllib.parse.parse_qs(p.query)
    if not (path.startswith('/api/') or path.startswith('/media/')):
        return False
    try:
        if method == 'GET':
            if path == '/api/config':
                h.send(200, _public_config()); return True
            if path == '/api/services':
                h.send(200, service_status()); return True
            if path == '/api/settings':
                d = settings_public()
                d['script_providers'], d['voice_providers'], d['image_providers'], d['motion_providers'] = SCRIPT_PROVIDERS, VOICE_PROVIDERS, IMAGE_PROVIDERS, MOTION_PROVIDERS
                try:
                    d['ollama_models'] = ollama_models()
                except Exception:
                    d['ollama_models'] = []
                h.send(200, d); return True
            if path == '/api/series':
                h.send(200, sorted((series_summary(s) for s in SERIES.values()), key=lambda s: s['created'], reverse=True)); return True
            m = re.fullmatch(r'/api/series/([a-f0-9]+)', path)
            if m:
                s = SERIES.get(m.group(1))
                if not s:
                    h.send(404, {'error': 'Série não encontrada'}); return True
                h.send(200, series_summary(s)); return True
            if path == '/api/videos':
                sid = (q.get('series') or [None])[0]
                vids = [v for v in VIDEOS.values() if not sid or v['series_id'] == sid]
                h.send(200, [_video_public(v) for v in sorted(vids, key=lambda v: v['created'], reverse=True)]); return True
            m = re.fullmatch(r'/api/videos/([a-f0-9]+)', path)
            if m:
                v = VIDEOS.get(m.group(1))
                if not v:
                    h.send(404, {'error': 'Vídeo não encontrado'}); return True
                h.send(200, _video_public(v)); return True
            if path == '/api/styles':
                h.send(200, [dict(s, preview=style_preview_url(s['id']), job=STYLE_JOBS.get(s['id'])) for s in STYLES_LIST]); return True
            if path == '/api/voices':
                h.send(200, list_voices()); return True
            if path == '/api/voice-preview':
                f = voice_preview((q.get('voice') or ['default'])[0], (q.get('lang') or ['pt-BR'])[0],
                                  (q.get('provider') or [None])[0])
                serve_file(h, f); return True
            if path == '/api/music':
                h.send(200, list_music()); return True
            m = re.fullmatch(r'/media/videos/([a-f0-9]+)/([A-Za-z0-9_.-]+)', path)
            if m:
                v = VIDEOS.get(m.group(1))
                f = VIDEOS_DIR / m.group(1) / m.group(2)
                dl = None
                if v and q.get('download') and m.group(2) == 'final.mp4':
                    dl = _safe(v.get('title') or 'video') + '.mp4'
                serve_file(h, f, dl); return True
            m = re.fullmatch(r'/api/music/([^/]+)/loop-preview', path)
            if m:
                serve_file(h, music_loop_preview(m.group(1))); return True
            m = re.fullmatch(r'/media/music/([^/]+)', path)
            if m:
                name = urllib.parse.unquote(m.group(1))
                f = (MUSIC_DIR / name)
                if f.resolve().parent != MUSIC_DIR.resolve():
                    h.send(404, {'error': 'inválido'}); return True
                serve_file(h, f); return True
            if path == '/media/test_image.png':
                serve_file(h, DATA / 'test_image.png'); return True
            m = re.fullmatch(r'/media/cast/([a-f0-9]+)/([A-Za-z0-9_.-]+\.png)', path)
            if m:
                serve_file(h, CAST_DIR / m.group(1) / m.group(2)); return True
            m = re.fullmatch(r'/media/videos/([a-f0-9]+)/elenco/([A-Za-z0-9_.-]+\.png)', path)
            if m:
                serve_file(h, VIDEOS_DIR / m.group(1) / 'elenco' / m.group(2)); return True
            m = re.fullmatch(r'/media/styles/([a-z0-9_]+)\.png', path)
            if m:
                serve_file(h, STYLE_PREV / f'{m.group(1)}.png'); return True
            return False

        if method == 'POST':
            mine = path in ('/api/series', '/api/settings', '/api/music/upload', '/api/styles', '/api/providers/test') or path.startswith(
                ('/api/series/', '/api/videos/', '/api/styles/', '/api/music/'))
            if not mine:
                return False
            m = re.fullmatch(r'/api/music/([^/]+)/(meta|delete)', path)
            if m and m.group(1) != 'upload':
                f = music_file(m.group(1))
                data = _read_json(h)
                if m.group(2) == 'delete':
                    f.unlink()
                    MUSIC_META.pop(f.name, None)
                else:
                    meta = MUSIC_META.setdefault(f.name, {})
                    if 'name' in data:
                        meta['name'] = str(data['name']).strip()[:80]
                    if 'tags' in data:
                        tags = data['tags'] if isinstance(data['tags'], list) else str(data['tags']).split(',')
                        meta['tags'] = [str(t).strip().lower()[:24] for t in tags if str(t).strip()][:8]
                _save('music.json', MUSIC_META)
                h.send(200, {'ok': True}); return True
            if path == '/api/music/upload':
                name = urllib.parse.unquote(h.headers.get('X-Filename', 'musica.mp3'))
                name = _safe(Path(name).name, 100)
                if Path(name).suffix.lower() not in ('.mp3', '.wav', '.m4a', '.ogg', '.aac', '.flac'):
                    raise ValueError('Formato de áudio não suportado (use MP3, WAV, M4A, OGG, AAC ou FLAC)')
                size = int(h.headers.get('Content-Length', '0') or 0)
                if size <= 0 or size > 80_000_000:
                    raise ValueError('Arquivo vazio ou maior que 80 MB')
                dest = MUSIC_DIR / name
                with dest.open('wb') as f:
                    left = size
                    while left > 0:
                        chunk = h.rfile.read(min(262144, left))
                        if not chunk:
                            break
                        f.write(chunk)
                        left -= len(chunk)
                h.send(201, {'file': dest.name}); return True
            data = _read_json(h)
            if path == '/api/series':
                h.send(201, create_series(data)); return True
            m = re.fullmatch(r'/api/series/([a-f0-9]+)/cast', path)
            if m:
                s = SERIES.get(m.group(1))
                if not s:
                    h.send(404, {'error': 'Série não encontrada'}); return True
                cast = []
                for c in data.get('cast', [])[:12]:
                    name, look = str(c.get('name', '')).strip()[:60], str(c.get('look', '')).strip()[:600]
                    if name and look:
                        cast.append({'name': name, 'look': look})
                old = {c['name'].lower(): c['look'] for c in s.get('cast', [])}
                for c in cast:                      # aparência mudou: refaz a ficha na próxima geração
                    if old.get(c['name'].lower()) not in (None, c['look']):
                        for p in (CAST_DIR / s['id']).glob(_char_slug(c['name']) + '__*.png'):
                            p.unlink(missing_ok=True)
                with LOCK:
                    s['cast'] = cast
                save_series()
                h.send(200, series_summary(s)); return True
            m = re.fullmatch(r'/api/series/([a-f0-9]+)(?:/(generate|delete))?', path)
            if m:
                sid, action = m.groups()
                s = SERIES.get(sid)
                if not s:
                    h.send(404, {'error': 'Série não encontrada'}); return True
                if action == 'generate':
                    raw_overrides = data.get('overrides') or {}
                    validated = validate_series(raw_overrides, partial=True) if raw_overrides else {}
                    allowed = series_config(s).keys()
                    overrides = {k: validated[k] for k in allowed if k in validated}
                    h.send(201, _video_public(enqueue_video(sid, config_override=overrides))); return True
                if action == 'delete':
                    with LOCK:
                        SERIES.pop(sid, None)
                        for vid in [k for k, v in VIDEOS.items() if v['series_id'] == sid]:
                            if vid in QUEUE:
                                QUEUE.remove(vid)
                            CANCEL.add(vid)
                    save_series()
                    h.send(200, {'ok': True}); return True
                upd = validate_series(data, partial=True)
                with LOCK:
                    s.update(upd)
                save_series()
                h.send(200, series_summary(s)); return True
            m = re.fullmatch(r'/api/videos/([a-f0-9]+)/(retry|cancel|pause|delete)', path)
            if m:
                vid, action = m.groups()
                if action == 'retry':
                    h.send(200, _video_public(retry_video(vid)))
                elif action == 'cancel':
                    h.send(200, _video_public(cancel_video(vid)))
                elif action == 'pause':
                    h.send(200, _video_public(pause_video(vid)))
                else:
                    delete_video(vid)
                    h.send(200, {'ok': True})
                return True
            if path == '/api/styles':
                h.send(200, save_style(data)); return True
            if path == '/api/styles/reset':
                with LOCK:
                    STYLES_LIST[:] = json.loads(json.dumps(ART_STYLES))
                save_styles()
                for p in STYLE_PREV.glob('*.png'):
                    p.unlink(missing_ok=True)
                STYLE_JOBS.clear()
                h.send(200, {'ok': True}); return True
            m = re.fullmatch(r'/api/styles/([a-z0-9_]+)/(preview|delete|up|down)', path)
            if m:
                sid, action = m.groups()
                if action == 'preview':
                    style_preview(sid)
                elif action == 'delete':
                    delete_style(sid)
                else:
                    move_style(sid, -1 if action == 'up' else 1)
                h.send(202, {'ok': True}); return True
            if path == '/api/providers/test':
                h.send(200, test_provider(data.get('kind') if data.get('kind') in ('script', 'image', 'motion') else 'voice')); return True
            if path == '/api/settings':
                for k in SECRET_KEYS:                 # chave vazia = manter a atual; "-" = apagar
                    if k in data:
                        val = str(data.pop(k) or '').strip()
                        if val == '-':
                            SETTINGS[k] = ''
                        elif val:
                            SETTINGS[k] = val
                for k in ('script_provider', 'voice_provider', 'openai_model', 'gemini_model', 'compat_base_url',
                          'compat_model', 'eleven_model', 'kie_model', 'kie_script_model', 'kie_image_model', 'image_provider', 'motion_provider', 'kie_motion_resolution', 'openai_image_model', 'openai_image_quality',
                          'fal_image_model', 'fal_motion_model', 'replicate_image_model', 'replicate_motion_model',
                          'gemini_image_model'):
                    if k in data:
                        SETTINGS[k] = str(data[k] or '').strip()[:300]
                if SETTINGS['script_provider'] not in SCRIPT_PROVIDERS:
                    SETTINGS['script_provider'] = 'ollama'
                if SETTINGS['voice_provider'] not in VOICE_PROVIDERS:
                    SETTINGS['voice_provider'] = 'voicestudio'
                if SETTINGS['image_provider'] not in IMAGE_PROVIDERS:
                    SETTINGS['image_provider'] = 'comfyui'
                if SETTINGS.get('motion_provider') not in MOTION_PROVIDERS:
                    SETTINGS['motion_provider'] = 'comfyui'
                if SETTINGS.get('kie_motion_resolution') not in ('480p', '720p'):
                    SETTINGS['kie_motion_resolution'] = '720p'
                if SETTINGS['openai_image_quality'] not in ('low', 'medium', 'high', 'auto'):
                    SETTINGS['openai_image_quality'] = 'medium'
                if 'image_parallel' in data:
                    SETTINGS['image_parallel'] = max(1, min(8, int(data['image_parallel'] or 3)))
                for k, typ in (('ollama_model', str), ('tts_model', str), ('lead_hours', float), ('image_width', int),
                               ('image_height', int), ('motion_max_frames', int), ('music_volume', float),
                               ('keep_work_files', bool), ('animate_all_scenes', bool)):
                    if k in data:
                        SETTINGS[k] = typ(data[k])
                if SETTINGS['image_width'] % 16 or SETTINGS['image_height'] % 16:
                    raise ValueError('Largura e altura devem ser múltiplos de 16')
                SETTINGS['motion_max_frames'] = max(49, ((int(SETTINGS['motion_max_frames']) - 1) // 8) * 8 + 1)
                _save('settings.json', SETTINGS)
                h.send(200, settings_public()); return True
            return False
    except (ValueError, RuntimeError, TimeoutError) as exc:
        h.send(400 if isinstance(exc, ValueError) else 502, {'error': str(exc)})
        return True
    return False


# Narrative workflow extension
import narrative as _narrative
import sys as _sys
_narrative.install(_sys.modules[__name__])

# ACE-Step instrumental music library extension
import music_generation as _music_generation
_music_generation.install(_sys.modules[__name__])

# Trilha sonora automática por vídeo (ACE-Step a partir do roteiro)
import score as _score
_score.install(_sys.modules[__name__])
