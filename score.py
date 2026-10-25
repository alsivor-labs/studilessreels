"""Trilha sonora automática: compõe uma música instrumental (ACE-Step, pelo ComfyUI) para cada vídeo,
a partir do roteiro aprovado, com a duração exata do vídeo. Somente biblioteca padrão."""
import json
import math
import re

NOTES = ('C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B')
KEYS = [f'{n} {m}' for n in NOTES for m in ('major', 'minor')]
FALLBACK = {
    'horror': {'name': 'Terror', 'bpm': 60, 'prompt': 'Dark cinematic horror underscore, sparse low piano, ominous sustained strings, unsettling ambient drones, slow rising tension, restrained percussion, background soundtrack for spoken narration'},
    'suspense': {'name': 'Suspense', 'bpm': 80, 'prompt': 'Cinematic suspense underscore, muted ticking percussion, pulsing low synth, tense strings, gradual tension build, subtle dynamics, background soundtrack for spoken narration'},
    'mystery': {'name': 'Mistério', 'bpm': 75, 'prompt': 'Mysterious cinematic underscore, delicate minor-key piano, soft sustained strings, subtle investigative atmosphere, spacious arrangement, background soundtrack for spoken narration'},
    'emotional': {'name': 'Emocional', 'bpm': 70, 'prompt': 'Emotional cinematic underscore, gentle warm piano, soft strings, tender hopeful progression, delicate dynamics, spacious arrangement, background soundtrack for spoken narration'},
}


def install(p):
    try:
        import music_generation
        FALLBACK.update({k: v for k, v in music_generation.PRESETS.items() if k in FALLBACK})
    except Exception:
        pass

    def brief(cfg, script, total=None):
        """Direção musical escrita pela IA a partir do roteiro (com reserva por gênero se falhar)."""
        plan = script.get('plan') or {}
        scenes = [s for s in script.get('scenes', []) if not s.get('cta')]
        spoken_story = '\n'.join(str(s.get('narration', '')).strip() for s in scenes if s.get('narration'))
        visual_arc = [{'scene':i+1, 'action':str(s.get('action', ''))[:400],
                       'emotion':str(s.get('emotion', ''))[:160],
                       'setting':str(s.get('environment', ''))[:160]} for i,s in enumerate(scenes)]
        ctx = {
            'niche': str(cfg.get('niche', ''))[:800],
            'title': script.get('title'),
            'summary': script.get('summary') or script.get('description', ''),
            'complete_spoken_story_in_order': spoken_story[:30000],
            'visual_story_arc_in_order': visual_arc,
            'genre': plan.get('genre'),
            'tension_progression': plan.get('tension_progression'),
            'final_emotion': plan.get('final_emotion'),
            'duration_seconds': round(float(total), 1) if total else None,
            'language': cfg.get('language'),
        }
        prompt = (
            'You are the composer of the background underscore for a short narrated vertical video. '
            'Read the complete spoken story and visual story arc from beginning to end before composing. '
            'Make the musical events follow what actually happens in this specific video; do not rely on genre alone. '
            'Read the story and return ONLY JSON {"tags": "...", "bpm": 72, "keyscale": "E minor", "mood": "..."}.\n'
            '- tags: 25 to 60 English words, comma separated, for a text-to-music model: style/genre, 3 to 5 instruments, '
            'mood, energy, and the emotional ARC over time following the scene emotions in order '
            '(for example "starts sparse and quiet, slowly builds tension, peaks near the end, soft resolution").\n'
            '- The music plays UNDER a narrator: instrumental, no vocals, no choir words, no lead melody that competes with '
            'speech, steady and unobtrusive, no sudden loud hits. Match the tone of the story (comedy = playful light '
            'instruments; horror = dark drones; emotional = warm piano and strings...).\n'
            '- bpm: integer between 50 and 140.\n'
            '- keyscale: exactly one of: ' + ', '.join(KEYS) + '.\n'
            '- mood: 2 to 4 words in Brazilian Portuguese describing the track.\n'
            'STORY: ' + json.dumps(ctx, ensure_ascii=False))
        try:
            text, model = p.llm_chat(prompt, 0.5, timeout=300)
            d = p._extract_json(text)
            tags = re.sub(r'\s+', ' ', str(d.get('tags', ''))).strip(' ,')[:900]
            if len(tags.split()) < 6:
                raise ValueError('direção musical curta demais')
            try:
                bpm = int(round(float(d.get('bpm'))))
            except (TypeError, ValueError):
                bpm = 75
            key = str(d.get('keyscale', '')).strip().lower()
            key = next((k for k in KEYS if k.lower() == key), None)
            return {'tags': tags, 'bpm': max(50, min(140, bpm)), 'keyscale': key,
                    'mood': str(d.get('mood', '')).strip()[:60], 'source': model}
        except Exception as exc:
            preset = FALLBACK.get(plan.get('genre') or '', FALLBACK['emotional'])
            return {'tags': preset['prompt'], 'bpm': preset['bpm'], 'keyscale': None, 'mood': preset['name'],
                    'source': 'padrão do gênero', 'note': str(exc)[:200]}

    def generate_score(v, cfg, script, total, work, cancelled):
        """Compõe (ou reaproveita) score.mp3 com pelo menos `total` segundos."""
        out = work / 'score.mp3'
        if out.is_file() and (p.ffprobe_duration(out) or 0) >= total - 0.5:
            return out
        if not hasattr(p, 'build_music_workflow'):
            raise RuntimeError('Integração ACE-Step não carregada (music_generation.py)')
        p._upd(v, status='music', progress=86)
        sc = script.get('score') or {}
        if not sc.get('tags'):
            sc = brief(cfg, script, total)
            script['score'] = sc
            p._upd(v, script=script)
        if cancelled():
            raise InterruptedError('cancelado')
        seconds = int(min(180, max(10, math.ceil(total + 1.5))))
        job = {'id': v['id'], 'prompt': sc['tags'], 'seconds': seconds, 'bpm': int(sc['bpm']),
               'seed': int(v.get('seed') or 1) % 4294967295}
        wf = p.build_music_workflow(job)
        if sc.get('keyscale') and 'keyscale' in wf['94']['inputs']:
            wf['94']['inputs']['keyscale'] = sc['keyscale']
        wf['104']['inputs']['filename_prefix'] = 'HistoriasStudio/music/score_' + v['id']
        lock = getattr(p, 'MEDIA_GPU_LOCK', None)
        if lock:
            lock.acquire()
        try:
            prepare = getattr(p, 'prepare_audio_generation_gpu', None)
            if prepare:
                try:
                    prepare()                  # libera Ollama, voz e outros modelos antes do ACE-Step
                except Exception:
                    pass
            outputs = p.comfy_run(wf, timeout=1800, cancelled=cancelled)
        finally:
            if lock:
                lock.release()
        files = p.comfy_files(outputs, ('.mp3', '.wav', '.flac', '.ogg'))
        if not files:
            raise RuntimeError('O ACE-Step terminou sem devolver áudio')
        blob = p.comfy_fetch(files[0])
        tmp = work / ('score_tmp' + p.Path(files[0]['filename']).suffix.lower())
        tmp.write_bytes(blob)
        if not p.ffprobe_duration(tmp):
            raise RuntimeError('A trilha gerada não é um áudio válido')
        if tmp.suffix != '.mp3':
            p.ffmpeg(['-i', tmp.name, '-c:a', 'libmp3lame', '-q:a', '2', out.name], work, 'trilha')
            tmp.unlink(missing_ok=True)
        else:
            p.os.replace(tmp, out)
        sc['duration'] = round(p.ffprobe_duration(out) or 0, 2)
        script['score'] = sc
        p._upd(v, script=script)
        return out

    p.generate_score = generate_score
    p.score_brief = brief
