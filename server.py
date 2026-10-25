import json, os, threading, time, uuid, urllib.request, urllib.parse, urllib.error, base64, re, mimetypes, subprocess, shutil, wave, io, struct
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
import pipeline
ROOT=Path(__file__).resolve().parent
HOST=os.getenv('HOST','0.0.0.0'); PORT=int(os.getenv('PORT','8787'))
COMFY=os.getenv('COMFY_URL','http://127.0.0.1:8188').rstrip('/')
VOICE=os.getenv('VOICE_URL','http://127.0.0.1:3900').rstrip('/')
OLLAMA=os.getenv('OLLAMA_URL','http://127.0.0.1:11434').rstrip('/')
AUDIO_DIR=ROOT/'audio'; AUDIO_DIR.mkdir(exist_ok=True)
SAMPLE_TEXT='Olá! Esta é uma demonstração da voz selecionada para o Histórias Studio.'
DEFAULT=json.loads((ROOT/'workflow.json').read_text(encoding='utf-8'))
lock=threading.RLock(); jobs={}; queue=[]; active=None; narrations={}
NEG=DEFAULT['71']['inputs']['text']
def call(path, data=None, method=None):
    body=json.dumps(data).encode() if data is not None else None
    req=urllib.request.Request(COMFY+path,data=body,headers={'Content-Type':'application/json'} if body else {},method=method)
    with urllib.request.urlopen(req,timeout=25) as r: return json.loads(r.read())
def external(base,path,data=None,timeout=90,raw=False):
    body=json.dumps(data,ensure_ascii=False).encode('utf-8') if data is not None else None
    headers={'Authorization':'Bearer local'}
    if body is not None: headers['Content-Type']='application/json'
    req=urllib.request.Request(base+path,data=body,headers=headers)
    try:
        with urllib.request.urlopen(req,timeout=timeout) as resp:
            payload=resp.read()
            return (payload,resp.headers.get('Content-Type','application/octet-stream')) if raw else json.loads(payload)
    except urllib.error.HTTPError as exc:
        detail=exc.read(1200).decode('utf-8','replace')
        raise RuntimeError(f'API retornou HTTP {exc.code}: {detail}') from exc

def plan_story(data):
    script=str(data.get('script','')).strip()
    if len(script)<30 or len(script)>25000: raise ValueError('Roteiro precisa ter entre 30 e 25.000 caracteres')
    count=int(data.get('count',12))
    if count<1 or count>40: raise ValueError('Quantidade de cenas inválida')
    model=str(data.get('model','qwen3:8b')).strip() or 'qwen3:8b'
    visual=str(data.get('style','cinematic 3D animated feature film, vertical 9:16, emotional storytelling'))[:700]
    instruction=f"""You are a film storyboard artist. Return ONLY valid JSON, no markdown or explanation, with exactly {count} items in "scenes". Each item has "narration" (the exact corresponding original-language excerpt from the original story, in sequence), "prompt" (detailed English image prompt, complete visual character identity for each recurring character, camera composition, emotion, location, lighting). Preserve character age, hair, clothing and physical traits across scenes. No text, no logos in images. Style: {visual}. Divide the COMPLETE original-language script in order, without rewriting or omitting its words. Script:\n{script}"""
    answer=external(OLLAMA,'/api/chat',{'model':model,'stream':False,'format':'json','messages':[{'role':'user','content':instruction}],'options':{'temperature':0.35}},timeout=300)
    content=answer.get('message',{}).get('content','')
    try: result=json.loads(content)
    except Exception: raise RuntimeError('O Ollama não retornou JSON válido. Tente novamente ou escolha outro modelo.')
    scenes=result.get('scenes',[])
    if not isinstance(scenes,list) or len(scenes)!=count or any(not isinstance(x,dict) or not str(x.get('prompt','')).strip() for x in scenes):
        raise RuntimeError('A IA não retornou a quantidade correta de cenas. Tente novamente.')
    normalize=lambda value: re.sub(r'\s+', ' ', value).strip()
    if normalize(' '.join(str(x.get('narration','')).strip() for x in scenes)) != normalize(script):
        raise RuntimeError('A divisão de cenas alterou ou omitiu palavras do roteiro. Tente novamente.')
    return {'scenes':[{'prompt':str(x['prompt']).strip(),'narration':str(x.get('narration','')).strip()} for x in scenes], 'model':model}

def audio_valid(blob):
    if blob[:4] == b'RIFF' and blob[8:12] == b'WAVE':
        try:
            with wave.open(io.BytesIO(blob),'rb') as wav:
                if wav.getnframes() == 0 or wav.getframerate() <= 0: raise ValueError('WAV vazio')
                return '.wav', wav.getnframes()/wav.getframerate()
        except Exception:
            # FFmpeg supports valid WAV formats that Python wave may not support (float etc.)
            if shutil.which('ffprobe'):
                probe=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration','-of','default=noprint_wrappers=1:nokey=1','pipe:0'],input=blob,capture_output=True,timeout=20)
                if probe.returncode==0:
                    try:
                        duration=float(probe.stdout.strip())
                        if duration>0:return '.wav',duration
                    except ValueError:pass
            raise RuntimeError('VoiceStudio retornou um WAV inválido ou sem quadros de áudio')
    if blob[:3]==b'ID3' or blob[:2] in (b'\xff\xfb',b'\xff\xf3',b'\xff\xf2'):
        if shutil.which('ffprobe'):
            probe=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration','-of','default=noprint_wrappers=1:nokey=1','pipe:0'],input=blob,capture_output=True,timeout=20)
            if probe.returncode==0:
                try:
                    duration=float(probe.stdout.strip())
                    if duration>0:return '.mp3',duration
                except ValueError:pass
        raise RuntimeError('Não foi possível validar o MP3. Verifique se o FFmpeg está instalado.')
    excerpt=blob[:350].decode('utf-8','replace')
    raise RuntimeError('VoiceStudio não retornou áudio reconhecível. Resposta: '+excerpt)

def synthesize(data):
    script=str(data.get('script','')).strip()
    if not script or len(script)>100000: raise ValueError('Informe um roteiro com até 100.000 caracteres')
    voice=str(data.get('voice','default')).strip() or 'default'
    model=str(data.get('model','tts-1')).strip() or 'tts-1'
    speed=float(data.get('speed',1.0))
    if not .25<=speed<=4: raise ValueError('Velocidade inválida')
    preview=bool(data.get('preview',False))
    if preview: script=pipeline.LANG.get(data.get('language'),pipeline.LANGUAGES[0])['sample']
    script=re.sub(r'\[(?:pause|whisper|silence|sussurro|pausa)[^\]]*\]', '', script, flags=re.I).strip()
    if not script: raise ValueError('O roteiro não contém texto narrável')
    pieces=[]; remaining=script
    while remaining:
        if len(remaining)<=3800: pieces.append(remaining); break
        cut=max(remaining.rfind('. ',0,3800),remaining.rfind('! ',0,3800),remaining.rfind('? ',0,3800),remaining.rfind('\n',0,3800))
        if cut<500: cut=remaining.rfind(' ',0,3800)
        if cut<500: cut=3800
        else: cut+=1
        pieces.append(remaining[:cut].strip()); remaining=remaining[cut:].strip()
    nid=uuid.uuid4().hex
    narration={'id':nid,'title':'Teste de voz' if preview else str(data.get('title','Narração'))[:140],'preview':preview,'status':'running','voice':voice,'model':model,'parts':len(pieces),'current':0,'created':time.strftime('%d/%m/%Y %H:%M'),'error':None,'files':[],'durations':[]}
    with lock: narrations[nid]=narration
    def worker():
        try:
            for i,piece in enumerate(pieces):
                payload={'model':model,'voice':voice,'input':piece,'response_format':'wav','speed':speed}
                blob,ctype=external(VOICE,'/v1/audio/speech',payload,timeout=900,raw=True)
                ext,duration=audio_valid(blob)
                filename=f'{nid}_parte_{i+1:02d}{ext}'
                (AUDIO_DIR/filename).write_bytes(blob)
                with lock:
                    narration['files'].append(filename); narration['durations'].append(round(duration,2)); narration['current']=i+1
            narration['status']='done'
        except Exception as exc:
            narration['status']='error'; narration['error']=str(exc)
    threading.Thread(target=worker,daemon=True).start()
    return narration

def run():
    global active
    while True:
        with lock:
            job=queue.pop(0) if queue else None
            if job: active=job['id']; job['status']='running'
        if not job: time.sleep(.4); continue
        try:
            for i,scene in enumerate(job['scenes']):
                if job.get('cancel'): break
                scene['status']='running'; job['current']=i+1
                wf=json.loads(json.dumps(DEFAULT))
                wf['67']['inputs']['text']=scene['prompt']; wf['71']['inputs']['text']=job['negative']
                wf['68']['inputs'].update(width=job['width'],height=job['height'],batch_size=1)
                wf['70']['inputs']['seed']=int(job['seed'])+i if job['seed'] is not None else int.from_bytes(os.urandom(5),'big')
                wf['9']['inputs']['filename_prefix']='HistoriasStudio/'+job['id'][:8]+'_cena_'+str(i+1).zfill(2)
                response=call('/prompt',{'prompt':wf,'client_id':job['id']})
                pid=response['prompt_id']; scene['prompt_id']=pid
                for _ in range(1800):
                    if job.get('cancel'): break
                    hist=call('/history/'+urllib.parse.quote(pid))
                    if pid in hist:
                        result=hist[pid]
                        if result.get('status',{}).get('status_str')=='error': raise RuntimeError('Erro de execução no ComfyUI: '+str(result.get('status',{}).get('messages',[]))[-400:])
                        images=[im for out in result.get('outputs',{}).values() for im in out.get('images',[])]
                        if not images: raise RuntimeError('Workflow terminou sem imagens')
                        scene['images']=images; scene['status']='done'; break
                    time.sleep(2)
                else: raise TimeoutError('Tempo limite excedido aguardando imagem')
                if job.get('cancel'): break
            job['status']='cancelled' if job.get('cancel') else 'done'
        except Exception as exc:
            job['status']='error'; job['error']=str(exc)
            if job['current']: job['scenes'][job['current']-1]['status']='error'
        finally:
            with lock: active=None
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def send(self,code,data,ctype='application/json'):
        raw=json.dumps(data,ensure_ascii=False).encode() if ctype=='application/json' else data
        self.send_response(code);self.send_header('Content-Type',ctype+'; charset=utf-8' if ctype.startswith('text/') else ctype);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    def do_GET(self):
        if pipeline.route(self,'GET'): return
        p=urllib.parse.urlparse(self.path)
        if p.path=='/api/voice/status':
            try:
                info=external(VOICE,'/health',timeout=5); self.send(200,{'connected':True,'info':info})
            except Exception as exc: self.send(200,{'connected':False,'error':str(exc)})
            return
        if p.path=='/api/voice/voices':
            try: self.send(200,external(VOICE,'/v1/audio/voices',timeout=15))
            except Exception as exc: self.send(502,{'error':str(exc)})
            return
        if p.path=='/api/ollama/models':
            try: self.send(200,external(OLLAMA,'/api/tags',timeout=8))
            except Exception as exc: self.send(502,{'error':str(exc)})
            return
        if p.path=='/api/narrations':
            with lock: self.send(200,list(reversed(list(narrations.values()))))
            return
        if p.path.startswith('/api/audio/'):
            filename=p.path.rsplit('/',1)[-1]
            if not re.fullmatch(r'[a-f0-9]{32}_parte_\d{2}\.(wav|mp3|bin)',filename): self.send(404,{'error':'Arquivo inválido'});return
            file=AUDIO_DIR/filename
            if not file.is_file(): self.send(404,{'error':'Não encontrado'});return
            ctype='audio/wav' if filename.endswith('.wav') else 'audio/mpeg' if filename.endswith('.mp3') else 'application/octet-stream'
            # Browser players require byte-range responses for reliable seeking and duration detection.
            size=file.stat().st_size
            byte_range=self.headers.get('Range','')
            match=re.fullmatch(r'bytes=(\d*)-(\d*)',byte_range.strip()) if byte_range else None
            if byte_range and not match:
                self.send_response(416);self.send_header('Content-Range',f'bytes */{size}');self.end_headers();return
            start=0;end=size-1
            if match:
                first,last=match.groups()
                if not first and not last:
                    self.send_response(416);self.send_header('Content-Range',f'bytes */{size}');self.end_headers();return
                if first: start=int(first);end=min(int(last),size-1) if last else size-1
                else: start=max(0,size-int(last))
                if start>=size or start>end:
                    self.send_response(416);self.send_header('Content-Range',f'bytes */{size}');self.end_headers();return
            self.send_response(206 if match else 200)
            self.send_header('Content-Type',ctype)
            self.send_header('Accept-Ranges','bytes')
            self.send_header('Cache-Control','no-store')
            self.send_header('Content-Length',str(end-start+1))
            if match:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
            self.end_headers()
            with file.open('rb') as stream:
                stream.seek(start);remaining=end-start+1
                while remaining>0:
                    chunk=stream.read(min(65536,remaining))
                    if not chunk:break
                    self.wfile.write(chunk);remaining-=len(chunk)
            return
        if p.path=='/api/status':
            try: info=call('/system_stats'); connected=True
            except Exception: connected=False; info={}
            self.send(200,{'connected':connected,'comfy_url':COMFY,'active':active,'queued':len(queue)});return
        if p.path=='/api/jobs':
            with lock: self.send(200,list(reversed(list(jobs.values()))));return
        if p.path.startswith('/api/image/'):
            parts=p.path.split('/'); jid=parts[3] if len(parts)>3 else ''; idx=int(parts[4]) if len(parts)>4 and parts[4].isdigit() else -1
            try:
                im=jobs[jid]['scenes'][idx]['images'][0]
                query=urllib.parse.urlencode({'filename':im['filename'],'subfolder':im.get('subfolder',''),'type':im.get('type','output')})
                with urllib.request.urlopen(COMFY+'/view?'+query,timeout=30) as resp: blob=resp.read();ctype=resp.headers.get('Content-Type','image/png')
                self.send(200,blob,ctype)
            except Exception as e:self.send(404,{'error':str(e)})
            return
        path=ROOT/'static'/('index.html' if p.path=='/' else p.path.lstrip('/'))
        if not path.resolve().is_relative_to((ROOT/'static').resolve()) or not path.is_file():self.send(404,{'error':'Not found'});return
        types={'.html':'text/html','.css':'text/css','.js':'application/javascript','.svg':'image/svg+xml','.png':'image/png','.ico':'image/x-icon'}
        self.send(200,path.read_bytes(),types.get(path.suffix,'application/octet-stream'))
    def do_POST(self):
        try:
            if pipeline.route(self,'POST'): return
            data=json.loads(self.rfile.read(min(int(self.headers.get('Content-Length','0')),1000000)))
            if self.path=='/api/plan':
                self.send(200,plan_story(data));return
            if self.path=='/api/narrations':
                self.send(201,synthesize(data));return
            if self.path=='/api/jobs':
                scenes=data.get('scenes',[])
                if not isinstance(scenes,list) or not 1<=len(scenes)<=40 or any(not isinstance(s,dict) or not str(s.get('prompt','')).strip() for s in scenes):raise ValueError('Informe entre 1 e 40 cenas com prompts')
                width=int(data.get('width',768));height=int(data.get('height',1344))
                if width<256 or height<256 or width>2048 or height>2048 or width%16 or height%16:raise ValueError('Resolução inválida (múltiplos de 16)')
                jid=str(uuid.uuid4()); job={'id':jid,'title':str(data.get('title','Sem título'))[:140],'created':time.strftime('%d/%m/%Y %H:%M'),'status':'queued','current':0,'width':width,'height':height,'seed':int(data['seed']) if str(data.get('seed','')).strip() else None,'negative':str(data.get('negative',NEG)),'scenes':[{'prompt':s['prompt'],'status':'queued','images':[]} for s in scenes],'error':None}
                with lock: jobs[jid]=job;queue.append(job)
                self.send(201,job);return
            if self.path.startswith('/api/cancel/'):
                jid=self.path.rsplit('/',1)[-1]
                with lock:
                    if jid not in jobs: self.send(404,{'error':'Não encontrado'});return
                    jobs[jid]['cancel']=True
                    if jobs[jid] in queue: queue.remove(jobs[jid]);jobs[jid]['status']='cancelled'
                self.send(200,{'ok':True});return
            self.send(404,{'error':'Not found'})
        except Exception as e:self.send(400,{'error':str(e)})
if __name__=='__main__':
    threading.Thread(target=run,daemon=True).start()
    pipeline.start()
    print(f'Histórias Studio: http://localhost:{PORT} | ComfyUI: {COMFY} | Ollama: {OLLAMA} | VoiceStudio: {VOICE}',flush=True)
    print(f'Estúdio manual (versão anterior): http://localhost:{PORT}/estudio-manual.html',flush=True)
    ThreadingHTTPServer((HOST,PORT),Handler).serve_forever()
