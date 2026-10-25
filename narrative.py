"""Narrative planning, evidence review and scene-directed audio. Standard library only."""
import json, re, copy, threading, wave

PROFILES = {'horror': (115, .82, .65), 'suspense': (128, .9, .4),
            'mystery': (132, .93, .4), 'emotional': (128, .9, .5)}
CHECKS = ['hook', 'continuity', 'motivation', 'clues', 'contradictions', 'resolution',
          'ending', 'natural_language', 'read_aloud', 'visual_feasibility']
PLAN = ['theme', 'genre', 'protagonist', 'conflict', 'setting', 'inciting_event',
        'tension_progression', 'clues', 'revelation', 'explanation', 'ending', 'final_emotion']

PT_MARKERS = set('que de não nao uma um com para ele ela os as do da dos das em no na se mas foi era muito quando porque então entao seu sua'.split())
EN_MARKERS = set('the and was his her with that for you to of it in is he she they but when then their there'.split())
ES_MARKERS = set('el los las del que con por para una pero cuando entonces muy fue estaba'.split())
CTA_RE = re.compile(r'\b(inscrev\w*|se inscreva|siga (o|a|nosso|nossa|a página|o canal)|link na bio|curt[ae] e compartilh\w*|ative o sininho|subscribe|follow (us|for|the)|like and share|hit the bell)\b', re.I)


def local_checks(script, cfg, durations):
    """Verificações determinísticas que não dependem da IA. Devolve (issues, checks_que_falharam)."""
    issues, failed = [], set()
    scenes = [s for s in script.get('scenes', []) if not s.get('cta')]
    secs = durations.get(cfg.get('duration'), {}).get('seconds', 35)
    transcript = ' '.join(s.get('narration', '') for s in scenes)
    # 1. quantidade de cenas para a duração (a imagem não pode ficar parada tempo demais)
    min_scenes = max(3, round(secs / 9))
    if len(scenes) < min_scenes:
        failed.add('read_aloud')
        issues.append({'severity': 'critical', 'problem': f'Poucas cenas para a duração ({len(scenes)}; mínimo {min_scenes})',
                       'evidence': f'{len(scenes)} cenas para cerca de {secs} s de vídeo',
                       'correction': f'Split the story into at least {min_scenes} visual events (one new image every 4 to 9 seconds), keeping every spoken word in order.'})
    # 2. cena longa demais (mais de ~14 s parada na mesma imagem)
    for i, s in enumerate(scenes, 1):
        w = len(s.get('narration', '').split())
        if w > 40:
            issues.append({'severity': 'warning', 'problem': f'Cena {i} longa demais ({w} palavras)', 'evidence': s['narration'][:200],
                           'correction': f'Split scene {i} into two or more visual events.'})
    # 3. idioma da narração
    toks = re.findall(r"[a-zà-ÿ']+", transcript.lower())
    pt, en, es = (sum(t in M for t in toks) for M in (PT_MARKERS, EN_MARKERS, ES_MARKERS))
    lang = (cfg.get('language') or 'pt-BR')[:2]
    want = {'pt': pt, 'en': en, 'es': es}.get(lang)
    if want is not None and len(toks) >= 20 and want < max(pt, en, es) * 0.6:
        failed.add('natural_language')
        names = {'pt': 'português', 'en': 'inglês', 'es': 'espanhol'}
        issues.append({'severity': 'critical', 'problem': f'A narração não parece estar em {names[lang]}',
                       'evidence': transcript[:200], 'correction': f'Rewrite the whole spoken story natively in {cfg.get("language")}.'})
    # 4. chamada para seguir/inscrever dentro da história (a CTA é separada)
    m = CTA_RE.search(transcript)
    if m:
        failed.add('ending')
        issues.append({'severity': 'critical', 'problem': 'Pedido de "siga/inscreva-se" dentro da história',
                       'evidence': m.group(0), 'correction': 'Remove any call to action from the story; the CTA is added separately.'})
    # 5. frases repetidas
    seen, dup = set(), []
    for sent in re.split(r'(?<=[.!?])\s+', transcript):
        k = ' '.join(re.findall(r'\w+', sent.lower()))
        if len(k.split()) >= 5:
            if k in seen:
                dup.append(sent)
            seen.add(k)
    if dup:
        issues.append({'severity': 'warning', 'problem': 'Frase repetida na narração', 'evidence': dup[0][:200],
                       'correction': 'Remove the repeated sentence or rewrite it.'})
    # 6. cena sem texto falado
    if any(not s.get('narration', '').strip() for s in scenes):
        failed.add('read_aloud')
        issues.append({'severity': 'critical', 'problem': 'Cena sem texto narrado', 'evidence': '', 'correction': 'Every scene needs spoken narration.'})
    return issues, failed


def install(p):
    gpu_lock = threading.RLock()
    def serial(fn):
        def wrapped(*args, **kwargs):
            with gpu_lock: return fn(*args, **kwargs)
        return wrapped
    def release_voice():
        try: loaded=p.external(p.VOICE,'/model/loaded',timeout=10)
        except (p.urllib.error.URLError,TimeoutError): return
        for model in loaded.get('models',[]):
            mid=model.get('id') or model.get('model_id') if isinstance(model,dict) else model
            if mid: p.external(p.VOICE,'/model/unload/'+p.urllib.parse.quote(str(mid),safe=''),{},timeout=60,raw=True)
    def release_comfy():
        try: p.external(p.COMFY,'/free',{'unload_models':True,'free_memory':True},timeout=30,raw=True)
        except (p.urllib.error.URLError,TimeoutError): pass
    original_image=p.make_image
    def image(*args,**kwargs):
        if (kwargs.get('provider') or p.SETTINGS.get('image_provider','comfyui'))=='comfyui': release_voice()
        return original_image(*args,**kwargs)
    p.make_image=image
    old_image_prompt=p.build_image_prompt
    def image_prompt(cfg,script,scene):
        prompt=old_image_prompt(cfg,script,scene)
        for c in script.get('characters',[]):
            if c['name'] in scene.get('characters',[]) and c['look'] not in prompt:
                prompt+=' '+c['name']+': '+c['look']+'.'
        for env in script.get('environments',[]):
            if isinstance(env,dict) and env.get('name')==scene.get('environment'):
                prompt+=' '+str(env.get('look',''))
        return prompt
    p.build_image_prompt=image_prompt
    def ask(prompt, validate):
        error = ''
        for _ in range(3):
            with gpu_lock:
                if p.SETTINGS.get('script_provider','ollama')=='ollama':
                    release_voice();release_comfy()
                content, model = p.llm_chat(prompt + '\nValidation feedback: ' + error, .35)
            try:
                obj = p._extract_json(content)
                if isinstance(obj,dict) and not obj.get('title'):
                    for envelope in ('story','script','corrected_story','revised_story'):
                        nested=obj.get(envelope)
                        if isinstance(nested,dict) and nested.get('title') and nested.get('scenes'):
                            obj=nested;break
                validate(obj)
                return obj
            except (ValueError, TypeError, KeyError) as exc:
                error = str(exc)
        raise RuntimeError('Resposta estruturada inválida após 3 tentativas: ' + error)

    def plan_valid(x):
        if not isinstance(x, dict) or any(not x.get(k) for k in PLAN):
            raise ValueError('Planejamento incompleto: ' + ', '.join(PLAN))
        if x['genre'] not in PROFILES: raise ValueError('Gênero inválido')
        for key in ('theme','conflict','inciting_event','revelation','explanation','ending','final_emotion'):
            if not isinstance(x[key],str) or not x[key].strip(): raise ValueError('Campo textual inválido: '+key)
        if not isinstance(x['clues'],list) or not x['clues'] or any(not isinstance(c,dict) or not c.get('clue') or not c.get('payoff') for c in x['clues']):
            raise ValueError('clues precisa ser uma lista de {clue, payoff}')

    def script_valid(x):
        if not isinstance(x, dict) or not x.get('title') or not x.get('summary'):
            raise ValueError('Título e resumo obrigatórios')
        if any(not isinstance(x.get(k),str) for k in ('title','summary','description')):
            raise ValueError('Título, resumo e descrição devem ser texto')
        if not isinstance(x.get('hashtags'),list) or any(not isinstance(t,str) for t in x['hashtags']):
            raise ValueError('hashtags precisa ser uma lista de textos')
        scenes = x.get('scenes')
        if not isinstance(scenes, list) or not 2 <= len(scenes) <= 40:
            raise ValueError('Use de 2 a 40 acontecimentos visuais')
        if not isinstance(x.get('characters'), list) or not isinstance(x.get('environments'), list):
            raise ValueError('Fichas de personagens e ambientes obrigatórias')
        for c in x['characters']:
            if not isinstance(c, dict) or any(not isinstance(c.get(k),str) or not c[k].strip() for k in ('name','look')): raise ValueError('Ficha inválida')
        for env in x['environments']:
            if not isinstance(env,dict) or any(not isinstance(env.get(k),str) or not env[k].strip() for k in ('name','look')): raise ValueError('Ficha de ambiente inválida')
        names={c['name'] for c in x['characters']}
        places={e['name'] for e in x['environments']}
        for s in scenes:
            for k in ('narration', 'image_prompt', 'motion_prompt', 'environment', 'action', 'emotion', 'continuity', 'delivery'):
                if not isinstance(s.get(k), str) or not s[k].strip(): raise ValueError('Cena sem ' + k)
            if not isinstance(s.get('characters'), list): raise ValueError('Elenco da cena obrigatório')
            if any(name not in names for name in s['characters']): raise ValueError('Use os nomes exatos da ficha de personagens')
            if s['environment'] not in places: raise ValueError('Use o nome exato da ficha do ambiente')
            if len(s['narration']) > 3800 or re.search(r'\[[^\]]+\]|<[^>]+>', s['narration']):
                raise ValueError('Narração longa ou com marcações de direção')
            for k in ('pause_before', 'pause_after'):
                if type(s.get(k)) not in (int, float) or not 0 <= s[k] <= 3: raise ValueError('Pausa inválida')

    def review_valid(x):
        if not isinstance(x, dict) or not isinstance(x.get('checks'), dict): raise ValueError('Revisão incompleta')
        for key in CHECKS:
            c = x['checks'].get(key, {})
            if type(c.get('passed')) is not bool or not isinstance(c.get('evidence'), str) or not c['evidence'].strip():
                raise ValueError('Revisão sem evidência para ' + key)
        if not isinstance(x.get('issues'), list): raise ValueError('Lista de problemas obrigatória')
        for issue in x['issues']:
            if issue.get('severity') not in ('critical', 'warning') or not all(issue.get(k) for k in ('problem', 'evidence', 'correction')):
                raise ValueError('Problema sem evidência/correção')

    def review(script, cfg):
        history = list(script.get('review', {}).get('history', []))
        for attempt in range(3):
            script['story_text']=' '.join(s['narration'] for s in script['scenes'])
            candidate = {k:v for k,v in script.items() if k not in ('review', 'timing')}
            transcript=' '.join(s['narration'] for s in script['scenes'])
            def normalized(text):
                return ' '.join(text.translate(str.maketrans({'’':"'",'‘':"'",'“':'"','”':'"'})).split()).casefold()
            def evidence_valid(r):
                review_valid(r)
                for key,c in r['checks'].items():
                    if key not in ('hook','continuity','motivation','clues','resolution','ending'): continue
                    if c['passed'] and (not isinstance(c.get('quotes'),list) or not c['quotes'] or any(not isinstance(q,str) or len(q)<4 or normalized(q) not in normalized(transcript) for q in c['quotes'])):
                        raise ValueError('Check '+key+' must quote exact spoken words, never plan or image metadata')
            try:
                r = ask('Independently audit ONLY the spoken transcript. The viewer CANNOT read the plan, summary, prompts or metadata. '
                    'If a revelation, explanation, identity or resolution exists only in metadata, it is MISSING and MUST fail. '
                    'An offer to resolve something is NOT an actual resolution. Compare intended ending against what is actually said. '
                    'Return JSON {"checks": {' +
                    ', '.join('"'+k+'": {"passed": true, "evidence": "specific reasoning", "quotes": ["exact excerpt from transcript"]}' for k in CHECKS) +
                    '}, "issues": [{"severity":"critical|warning","problem":"...","evidence":"quote/scene", "correction":"concrete fix"}]}. '
                    'Verify causal knowledge, planted clues BEFORE revelation, definitive genre-appropriate resolution, native US English when requested, no CTA in story. '
                    'Never pass without reading every scene. SPOKEN TRANSCRIPT: '+transcript+'\nIntent and visual metadata (NOT proof of spoken facts): ' + json.dumps(candidate, ensure_ascii=False), evidence_valid)
            except (RuntimeError,p.urllib.error.URLError,TimeoutError) as exc:
                issue={'severity':'critical','problem':'Revisor sem evidências verificáveis','evidence':str(exc),'correction':'Solicite nova revisão ou edite o roteiro; aprovação automática bloqueada.'}
                script['review']={'approved':False,'checks':{},'issues':[issue],'history':history+[{'attempt':attempt+1,'approved':False,'issues':[issue]}]}
                script['estimated_duration']=round(sum(len(s['narration'].split()) for s in script['scenes'])/PROFILES[script['plan']['genre']][0]*60,1)
                return script
            # Local guards also check observable failures the model may overlook.
            expected=p.DUR[cfg['duration']]['seconds']*PROFILES[script['plan']['genre']][0]/60
            words=len(transcript.split())
            if words<expected*.7 or words>expected*1.5:
                r['checks']['read_aloud']['passed']=False
                r['issues'].append({'severity':'critical','problem':'Extensão incompatível com a duração e o ritmo escolhidos',
                                    'evidence':f'{words} palavras; referência de {round(expected)} palavras.',
                                    'correction':f'Write approximately {round(expected)} spoken words. Expand actual events, clues, explanation and definitive outcome, not visual metadata.'})
            ending=script['scenes'][-1]['narration']
            sentences=[s.strip(' \t\n\"\'') for s in re.split(r'[.!?]+',ending) if s.strip(' \t\n\"\'')]
            last_sentence=sentences[-1] if sentences else ending
            if re.search(r'\b(ready to|about to|preparing to|prepared to|can work (?:it|this) out|pront[oa] para|prestes a|se preparou para)\b',last_sentence,re.I):
                r['checks']['ending']['passed']=False
                r['issues'].append({'severity':'critical','problem':'O final anuncia uma ação ou proposta sem confirmar o resultado',
                                    'evidence':ending,'correction':'Narrate the actual outcome of the central conflict after this intention; do not end at readiness, an offer or a future action.'})
            extra, failed = local_checks(script, cfg, p.DUR)
            for key in failed:
                if key in r['checks']:
                    r['checks'][key]['passed'] = False
            r['issues'].extend(extra)
            approved = all(c['passed'] for c in r['checks'].values()) and not any(i['severity']=='critical' for i in r['issues'])
            history.append({'attempt': attempt+1, 'checks': r['checks'], 'issues': r['issues'], 'approved': approved})
            if approved or attempt == 2:
                script['review'] = dict(r, approved=approved, history=history)
                script['estimated_duration'] = round(sum(len(s['narration'].split()) for s in script['scenes']) / PROFILES[script['plan']['genre']][0] * 60, 1)
                return script
            identities={c['name']:c['look'] for c in script['characters']}
            duration_issue = any(i.get('problem') == 'Extensão incompatível com a duração e o ritmo escolhidos'
                                 for i in r['issues'] if i.get('severity') == 'critical')
            target_scenes = set(range(len(script['scenes']))) if duration_issue else set()
            if not duration_issue:
                def norm(s): return ' '.join(re.findall(r"[\w']+", str(s).casefold()))
                for issue in r['issues']:
                    if issue.get('severity') != 'critical': continue
                    evidence = norm(issue.get('evidence', ''))
                    if not evidence: continue
                    for idx, scene in enumerate(script['scenes']):
                        speech = norm(scene.get('narration', ''))
                        if evidence in speech or speech in evidence:
                            target_scenes.add(idx)
                if not target_scenes:
                    issue = {'severity':'critical','problem':'Não foi possível localizar com segurança a cena para correção automática',
                             'evidence':'; '.join(str(i.get('evidence',''))[:160] for i in r['issues'] if i.get('severity')=='critical'),
                             'correction':'Edite somente a cena indicada e solicite nova revisão.'}
                    script['review']=dict(r,approved=False,issues=r['issues']+[issue],history=history)
                    script['estimated_duration']=round(sum(len(s['narration'].split()) for s in script['scenes'])/PROFILES[script['plan']['genre']][0]*60,1)
                    return script
            original_scenes = copy.deepcopy(script['scenes'])
            original_top = {k:copy.deepcopy(v) for k,v in script.items() if k not in ('scenes','story_text','review','timing')}
            def fixed_valid(x):
                script_valid(x)
                if any(c['name'] in identities and c['look']!=identities[c['name']] for c in x['characters']):
                    raise ValueError('Preserve as aparências das fichas existentes')
                if len(x['scenes']) != len(original_scenes):
                    raise ValueError('Preserve the number and order of scenes')
                for key, value in original_top.items():
                    if x.get(key) != value:
                        raise ValueError('Preserve all story-level fields; only repair the flagged scene text')
                for idx, (before, after) in enumerate(zip(original_scenes, x['scenes'])):
                    if idx not in target_scenes and after != before:
                        raise ValueError('Scene '+str(idx+1)+' is outside the reported issue; preserve it exactly')
                    if duration_issue and any(after.get(k) != before.get(k) for k in before if k != 'narration'):
                        raise ValueError('For a duration issue, change narration text only; preserve scene metadata')
            try:
                scope = ('The only issue to repair is story length. Keep the same scenes and order. Change ONLY narration text across scenes as needed to reach approximately '
                         +str(round(expected))+' spoken words; preserve every visual field, character, environment, ending, and all other story facts. ' if duration_issue else
                         'Repair only the critical issue(s) evidenced in the specified scene(s). Keep all other scenes and all story-level fields exactly unchanged. ')
                fixed = ask(scope+'Return ONLY the COMPLETE STORY object, not the audit and not a list of changes. '
                        'Required ROOT keys: title (string), description (string), hashtags (string array), summary (string), characters ([{name,look}]), '
                        'environments ([{name,look}]), scenes (array with narration,characters,environment,action,emotion,continuity,image_prompt,motion_prompt,delivery,pause_before,pause_after). '
                        'Keep its language. No CTA. Do not rewrite, improve, or paraphrase any unaffected scene. '
                        'Existing character looks are immutable. Target scene numbers (1-based): '+', '.join(str(i+1) for i in sorted(target_scenes))+'. '
                        'Issue(s): '+json.dumps([i for i in r['issues'] if i.get('severity')=='critical'],ensure_ascii=False)+' '
                        + json.dumps({'story':candidate}, ensure_ascii=False), fixed_valid)
            except (RuntimeError,p.urllib.error.URLError,TimeoutError) as exc:
                issue={'severity':'critical','problem':'Correção automática não concluída','evidence':str(exc),'correction':'Edite o roteiro ou solicite uma nova revisão.'}
                script['review']=dict(r,approved=False,issues=r['issues']+[issue],history=history)
                script['estimated_duration']=round(sum(len(s['narration'].split()) for s in script['scenes'])/PROFILES[script['plan']['genre']][0]*60,1)
                return script
            fixed['plan'] = script['plan']
            history[-1]['corrections'] = [f"Ajustada(s) apenas a(s) cena(s) {', '.join(str(i+1) for i in sorted(target_scenes))}" + (' (somente narração para duração).' if duration_issue else '.')]
            script = fixed

    def align(script):
        texts=[s['narration'] for s in script['scenes']]
        def validate(x):
            script_valid(x)
            if [s['narration'] for s in x['scenes']]!=texts: raise ValueError('Preserve cada trecho exato, em ordem')
        aligned=ask('Rebuild ONLY visual and delivery metadata to match these edited narration excerpts. Preserve every narration byte and scene order. '
                    'Return complete story JSON with characters [{name,look}], environments [{name,look}], title, summary, description, hashtags, scenes. '
                    'Each scene requires narration, characters (list of names), environment, action, emotion, continuity, image_prompt (English, full fixed identities), '
                    'motion_prompt (English), delivery, pause_before and pause_after (seconds 0..3). Story: '+json.dumps(script,ensure_ascii=False),validate)
        aligned['plan']=script['plan']
        aligned['review']=script.get('review',{})
        return aligned

    def write(cfg, previous, series=None):
        context = {'brief':cfg['niche'], 'language':cfg['language'], 'previous_titles':previous[-25:],
                   'cast':(series or {}).get('cast', []), 'episodes':(series or {}).get('episodes', [])[-10:],
                   'story_mode':(series or {}).get('story_mode'), 'reference':cfg.get('example')}
        plan = ask('Plan the END before writing. Return JSON with these required fields: ' + ', '.join(PLAN) +
                   '. genre must be horror, suspense, mystery or emotional. clues must be a nonempty list of {clue, payoff}. Include causal chain and explicit clue/payoff mapping. '
                   'Resolve the central conflict; no generic unexplained ending. Context: '+json.dumps(context, ensure_ascii=False), plan_valid)
        wpm = PROFILES[plan['genre']][0]
        schema = {'title':'...', 'description':'...', 'hashtags':[], 'summary':'...', 'characters':[{'name':'...', 'look':'fixed detailed English appearance/clothes/vehicle'}],
                  'environments':[{'name':'...', 'look':'fixed English setting'}], 'scenes':[{'narration':'exact spoken story excerpt', 'characters':['names'],
                  'environment':'setting', 'action':'visual event', 'emotion':'emotion', 'continuity':'connection to preceding scene',
                  'image_prompt':'English still, complete fixed identities, no text', 'motion_prompt':'English movement from that still',
                  'delivery':'restrained reading intention', 'pause_before':0.0, 'pause_after':0.4}]}
        draft_schema={k:v for k,v in schema.items() if k!='scenes'}
        draft_schema['story_text']='COMPLETE spoken story, including planted clues, revelation, explanation and definitive outcome. Not an outline.'
        def draft_valid(x):
            if not isinstance(x,dict) or not isinstance(x.get('story_text'),str) or len(x['story_text'].strip())<30:
                raise ValueError('story_text precisa conter a história completa narrável')
            if any(not x.get(k) for k in ('title','summary')): raise ValueError('Título e resumo obrigatórios')
            if re.search(r'\[[^\]]+\]|<[^>]+>',x['story_text']): raise ValueError('Sem marcações na fala')
        draft=ask('Write a COMPLETE spoken story before any storyboard. New original episode; avoid previous_titles. Write natively in '+cfg['language']+
                  ' (conversational US English for en-US; never translate from Portuguese). Target '+str(round(p.DUR[cfg['duration']]['seconds']*wpm/60))+
                  ' spoken words. Every important fact in the plan must actually be told to the listener, including the identity/revelation, its explanation and the completed outcome. '
                  'Do not stop at confronting someone, being ready, making an offer or calling for help; tell what actually happened. '
                  'No CTA, labels or acting instructions in story_text. Respect recurring cast and episode facts. Return JSON matching '+json.dumps(draft_schema)+
                  '\nContext: '+json.dumps(context,ensure_ascii=False)+'\nPLAN: '+json.dumps(plan,ensure_ascii=False),draft_valid)
        def storyboard_valid(x):
            script_valid(x)
            normalize=lambda text:' '.join(text.split())
            if normalize(' '.join(s['narration'] for s in x['scenes']))!=normalize(draft['story_text']):
                raise ValueError('O storyboard deve preservar TODAS as palavras de story_text, na mesma ordem, sem reescrever')
        script=ask('Build a storyboard from the COMPLETE approved-for-drafting text below. Split by visual events; number of scenes is flexible (2..40). '
                   'Copy exact consecutive excerpts into narration. Concatenating them MUST reproduce story_text word for word. Never summarize, omit or rewrite it. '
                   'Only visual and delivery metadata is new. Keep fixed characters/environments. For every scene, image_prompt must depict the exact narrated instant and visibly communicate its emotion through each character’s facial expression, gaze, posture and gesture; avoid generic neutral reactions. Track emotional changes across the story (for example grief, joy, fear, relief or determination), and at the climax, revelation or turning point show the strongest fitting reaction and immediate consequence. When no character is visible, let action, setting and lighting convey the emotion. Do not invent story events or break character/environment continuity. Return JSON matching '+json.dumps(schema)+
                   '\nSTORY: '+json.dumps(draft,ensure_ascii=False),storyboard_valid)
        script['plan'] = plan
        fixed={c['name'].lower():c['look'] for c in (series or {}).get('cast',[])}
        for c in script['characters']:
            if c['name'].lower() in fixed: c['look']=fixed[c['name'].lower()]
        return review(script, cfg)

    def unload():
        if p.SETTINGS.get('script_provider', 'ollama') == 'ollama':
            for m in p.external(p.OLLAMA, '/api/ps', timeout=10).get('models', []):
                p.external(p.OLLAMA, '/api/generate', {'model':m['name'], 'keep_alive':0}, timeout=60)

    def narrate(work, scenes, cfg, cancelled):
        genre = cfg.get('narration_profile', 'horror')
        target, auto_speed, pause = PROFILES.get(genre, PROFILES['horror'])
        speed = float(cfg.get('speed') or 1) if cfg.get('manual_speed') else auto_speed
        intensity = float(cfg.get('pause_intensity', 1))
        provider = cfg.get('voice_provider') or 'voicestudio'
        props = {}
        style_supported=False
        if provider == 'voicestudio':
            release_comfy()
            api = p.external(p.VOICE, '/openapi.json', timeout=10)
            props = api.get('components', {}).get('schemas', {}).get('SpeechRequest', {}).get('properties', {})
            engines=p.external(p.VOICE,'/engines/tts',timeout=10)
            backend=next((b for b in engines.get('backends',[]) if b.get('id')==engines.get('active')), {})
            style_supported=bool(backend.get('supports_emotion')) and 'instructions' in props
        parts, timing, offset = [], [], 0.0
        for i,s in enumerate(scenes):
            if cancelled(): raise InterruptedError('cancelado')
            text = re.sub(r'\[[^\]]*\]|<[^>]*>', '', s['narration']).strip()
            before = min(3, max(0,float(s.get('pause_before',0))))*intensity
            after = max(pause, min(3,max(0,float(s.get('pause_after',pause)))))*intensity
            direction=(s.get('emotion','')+' '+s.get('delivery','')).lower()
            dramatic=bool(re.search(r'revelation|discovery|climax|impact|revela|descoberta|clímax',direction))
            if dramatic: before=max(before,.45*intensity)
            if s.get('cta'): before = float(cfg.get('cta_gap',1))
            if s.get('screen_only'):
                import io
                buf=io.BytesIO()
                with wave.open(buf,'wb') as wav:
                    wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(44100)
                    wav.writeframes(b'\0\0'*round(max(2,len(text.split())/2)*44100))
                blob=buf.getvalue()
            elif provider == 'voicestudio':
                body = {'model':p.SETTINGS.get('tts_model') or 'tts-1', 'voice':cfg.get('voice') or 'default', 'input':text, 'response_format':'wav'}
                if 'speed' in props: body['speed'] = speed if cfg.get('manual_speed') else speed*(.94 if dramatic else 1.03 if 'urgent' in direction else 1)
                if 'language' in props: body['language'] = cfg.get('language','pt-BR').split('-')[0]
                if style_supported: body['instructions'] = s.get('delivery','Restrained natural storytelling')
                blob,_ = p.external(p.VOICE, '/v1/audio/speech',body,timeout=1800,raw=True)
            else: blob = p.tts(text,cfg.get('voice') or 'default',speed,provider)
            ext,dur = p.audio_valid(blob)
            # Calibrate by re-synthesizing; never stretch the finished waveform.
            if provider=='voicestudio' and 'speed' in props and not cfg.get('manual_speed') and not s.get('screen_only'):
                for retry in range(2):
                    measured_wpm=len(text.split())/max(.1,dur+before+after)*60
                    if target*.9 <= measured_wpm <= target*1.1: break
                    body['speed']=max(.4,min(1.4,body['speed']*target/measured_wpm))
                    blob,_=p.external(p.VOICE,'/v1/audio/speech',body,timeout=1800,raw=True)
                    ext,dur=p.audio_valid(blob)
            raw,part = f'directed_{i:02d}_source{ext}',f'directed_{i:02d}.wav'
            (work/raw).write_bytes(blob)
            p.ffmpeg(['-i',raw,'-af',f'adelay={round(before*1000)}:all=1,apad=pad_dur={after}', '-ar','44100','-ac','1','-c:a','pcm_s16le',part],work,'pausas por cena')
            measured = p.ffprobe_duration(work/part)
            if not measured or measured <= 0: raise RuntimeError('Áudio de cena vazio')
            timing.append({'start':round(offset,3),'speech_start':round(offset+before,3),'speech_end':round(offset+before+dur,3),'end':round(offset+measured,3)})
            s['duration'] = measured
            offset += measured
            parts.append(part)
        (work/'directed.txt').write_text(''.join("file '"+part+"'\n" for part in parts),encoding='utf-8')
        p.ffmpeg(['-f','concat','-safe','0','-i','directed.txt','-c:a','pcm_s16le','narration.wav'],work,'narração completa')
        duration = p.ffprobe_duration(work/'narration.wav')
        actual=round(sum(len(s['narration'].split()) for s in scenes if not s.get('screen_only'))/duration*60,1)
        return {'file':'narration.wav','duration':duration,'scenes':timing,'wpm':actual,'target_wpm':target,
                'config_signature':signature(cfg,scenes),
                'style_supported':style_supported,
                'warning':('O mecanismo não expõe velocidade nesta API; as pausas continuam disponíveis.' if provider=='voicestudio' and 'speed' not in props else
                           'A voz permaneceu fora da faixa de ritmo após as tentativas de síntese.' if not cfg.get('manual_speed') and not target*.9<=actual<=target*1.1 else None),
                'speed_supported':provider!='voicestudio' or 'speed' in props}

    def signature(cfg,scenes):
        return json.dumps({'config':{k:cfg.get(k) for k in ('voice','voice_provider','language','narration_profile','manual_speed','speed','pause_intensity','cta_gap')},
                           'text':[(s['narration'],s.get('pause_before'),s.get('pause_after'),s.get('screen_only')) for s in scenes]},sort_keys=True)

    original_produce, original_public, original_route = p.produce, p._video_public, p.route
    def produce(v):
        if not v.get('script'):
            p._upd(v,status='script',progress=3)
            script = write(v['config'],[x.get('title','') for x in p.VIDEOS.values() if x['series_id']==v['series_id']],p.SERIES.get(v['series_id']))
            p._upd(v,script=script,title=script['title'],description=script.get('description',''),hashtags=script.get('hashtags',[]))
            series=p.SERIES.get(v['series_id'])
            if series and series.get('story_mode')=='continuous':
                known={c['name'].lower() for c in series.setdefault('cast',[])}
                for char in script['characters']:
                    if char['name'].lower() not in known and len(series['cast'])<12:
                        series['cast'].append(copy.deepcopy(char));known.add(char['name'].lower())
                p.save_series()
        if not v['script'].get('plan'):
            legacy=copy.deepcopy(v['script'])
            legacy['plan']=ask('Infer the intended plan of this existing story. Return JSON fields '+', '.join(PLAN)+
                               '. genre: horror, suspense, mystery or emotional. Story: '+json.dumps(legacy,ensure_ascii=False),plan_valid)
            v['script']=review(align(legacy),v['config'])
            v['approved']=False
        if v['id'] in p.CANCEL: raise InterruptedError('cancelado')
        # The narrative reviewer already retries automatic corrections. Keep its
        # findings attached to the episode, but never block scheduled production
        # waiting for a person to approve the script.
        if not v.get('approved'):
            v['approved'] = True
            v['override_critical'] = True
            v['auto_approved'] = True
        unload()
        cfg = v['config']
        cfg['narration_profile'] = cfg.get('narration_profile') or v['script']['plan']['genre']
        if v['script'].get('timing',{}).get('config_signature')!=signature(cfg,v['script']['scenes']):
            v['script'].pop('timing',None)
        return original_produce(v)

    def public(v):
        out = original_public(v)
        out['scenes'] = copy.deepcopy((v.get('script') or {}).get('scenes',[]))
        out['narrative'] = {k:v.get('script',{}).get(k) for k in ('plan','summary','review','estimated_duration','timing')} if v.get('script') else None
        out['audio_url'] = f"/media/videos/{v['id']}/narration.wav?v={v.get('audio_version',0)}" if (p.VIDEOS_DIR/v['id']/'narration.wav').is_file() else None
        cfg=v.get('config',{})
        out['narration_config']={k:cfg.get(k) for k in ('narration_profile','manual_speed','speed','pause_intensity')}
        cta=next((s for s in (v.get('script') or {}).get('scenes',[]) if s.get('cta')),None)
        out['cta']={'enabled':bool(cta),'text':cta['narration'] if cta else '', 'narrated':not cta.get('screen_only') if cta else False,
                    'gap':cfg.get('cta_gap',1),'channel':cfg.get('channel_name','')}
        out['voice_preview_url']='/api/voice-preview?'+p.urllib.parse.urlencode({'voice':cfg.get('voice') or 'default','lang':cfg.get('language') or 'pt-BR','provider':cfg.get('voice_provider') or 'voicestudio'})
        return out

    def route(h, method):
        path = p.urllib.parse.urlparse(h.path).path
        m = re.fullmatch(r'/api/videos/([a-f0-9]+)/(approve|review|narrate)',path)
        if method != 'POST' or not m: return original_route(h,method)
        try:
            vid,action = m.groups()
            v = p.VIDEOS.get(vid)
            if not v or not v.get('script'): raise ValueError('Roteiro não encontrado')
            if v['status'] not in ('review','done','error','cancelled','paused'): raise ValueError('Aguarde a operação atual terminar')
            d = p._read_json(h)
            if action!='review' and not v['script'].get('plan'):
                raise ValueError('Roteiro antigo: solicite uma nova revisão para migrar antes de produzir ou narrar.')
            if action == 'review':
                texts = d.get('texts')
                script = copy.deepcopy(v['script'])
                script['scenes']=[s for s in script['scenes'] if not s.get('cta')]
                if texts is not None:
                    if not isinstance(texts,list) or len(texts)!=len(script['scenes']): raise ValueError('Quantidade de cenas alterada')
                    for s,t in zip(script['scenes'],texts): s['narration']=t
                    if script.get('plan'): script_valid(script)
                    elif any(not isinstance(t,str) or not t.strip() or len(t)>3800 for t in texts): raise ValueError('Trecho de narração inválido')
                script.pop('timing',None)
                v['approved']=False
                p._upd(v,status='script',step_label='Revisando roteiro',progress=5)
                def run_review():
                    try:
                        if not script.get('plan'):
                            script['plan']=ask('Infer intended narrative plan. Return JSON fields '+', '.join(PLAN)+
                                               '. genre: horror, suspense, mystery or emotional. clues: [{clue,payoff}]. Story: '+json.dumps(script,ensure_ascii=False),plan_valid)
                        # This editor changes spoken text only. Keep visual prompts and cached
                        # images/motion clips intact; only narration and final render need rebuilding.
                        revised=review(script if texts is not None else align(script),v['config'])
                        if vid in p.CANCEL: raise InterruptedError('cancelado')
                        work=p.VIDEOS_DIR/vid
                        if texts is None and work.is_dir():
                            archive=work/('revision_'+str(p.time.time_ns()));archive.mkdir()
                            for pattern in ('scene_*.png','motion_*.*'):
                                for file in work.glob(pattern): p.shutil.move(str(file),str(archive/file.name))
                        revised.pop('timing',None)
                        p._upd(v,script=revised,status='review',step_label='Revisão do roteiro',progress=8,file=None)
                    except InterruptedError: p._upd(v,status='cancelled',error=None)
                    except Exception as exc: p._upd(v,status='error',error=str(exc))
                    finally: p.CANCEL.discard(vid)
                threading.Thread(target=run_review,daemon=True).start()
            elif action == 'approve':
                if not v['script'].get('review',{}).get('approved') and d.get('override_critical') is not True:
                    raise ValueError('Revisão reprovada. Corrija ou confirme a exceção explícita.')
                v['approved']=True
                cfg=v['config']
                cfg.update(manual_speed=bool(d.get('manual_speed')),speed=max(.5,min(2,float(d.get('speed',1)))),pause_intensity=max(0,min(3,float(d.get('pause_intensity',1)))))
                cfg['narration_profile']=d.get('profile') if d.get('profile') in PROFILES else v['script']['plan']['genre']
                cta = str(d.get('cta_text','')).replace('{channel}',str(d.get('channel','')))[:500].strip()
                cfg['channel_name']=str(d.get('channel',''))[:120]
                v['config']['cta_gap']=max(0,min(5,float(d.get('cta_gap',1))))
                had_cta=any(s.get('cta') for s in v['script']['scenes'])
                v['script']['scenes']=[s for s in v['script']['scenes'] if not s.get('cta')]
                if had_cta: v['script'].pop('timing',None)
                if d.get('cta_enabled') and cta:
                    sc=copy.deepcopy(v['script']['scenes'][-1])
                    sc.update(narration=cta,cta=True,screen_only=not bool(d.get('cta_narrated')),pause_before=v['config']['cta_gap'],pause_after=.5)
                    v['script']['scenes'].append(sc)
                    v['script'].pop('timing',None)
                v['override_critical']=d.get('override_critical') is True
                p._upd(v,status='queued',error=None)
                with p.LOCK: p.QUEUE.append(vid)
            else:
                cfg=v['config']
                cfg.update(manual_speed=bool(d.get('manual_speed')),speed=max(.5,min(2,float(d.get('speed',1)))),pause_intensity=max(0,min(3,float(d.get('pause_intensity',1)))))
                cfg['narration_profile']=d.get('profile') if d.get('profile') in PROFILES else v['script']['plan']['genre']
                p._upd(v,status='voice',progress=10)
                def audio():
                    try:
                        with gpu_lock:
                            unload()
                            work=p.VIDEOS_DIR/vid; work.mkdir(parents=True,exist_ok=True)
                            v['script']['timing']=narrate(work,v['script']['scenes'],cfg,lambda:vid in p.CANCEL)
                        v['audio_version']=v.get('audio_version',0)+1
                        p._upd(v,status='review',step_label='Revisão do roteiro',progress=8)
                    except InterruptedError: p._upd(v,status='cancelled',error=None)
                    except Exception as exc: p._upd(v,status='error',error=str(exc))
                    finally: p.CANCEL.discard(vid)
                threading.Thread(target=audio,daemon=True).start()
            h.send(200,public(v))
        except (ValueError,RuntimeError,TypeError) as exc: h.send(400,{'error':str(exc)})
        return True
    p.write_script, p.narrate, p.produce, p._video_public, p.route = write, serial(narrate), serial(produce), public, route
    p.review_script=review
    p.STEPS['review']='Revisão do roteiro'
    p.MEDIA_GPU_LOCK=gpu_lock
    def prepare_audio_gpu():
        try: unload()
        except (p.urllib.error.URLError,TimeoutError): pass
        release_voice()
        release_comfy()
    p.prepare_audio_generation_gpu=prepare_audio_gpu




