import sys, json, copy, io, wave, tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pipeline as p, narrative
plan={k:'established cause' for k in narrative.PLAN};plan['genre']='horror';plan['clues']=[{'clue':'warm key','payoff':'recent intruder'}]
scene={'narration':'The key was warm. Someone had just used it. Sarah noticed wet footprints leading from the unlocked kitchen window to the hallway, where she heard a familiar cough behind the door.', 'characters':['Sarah'],'environment':'hall','action':'opens door','emotion':'fear','continuity':'same door','image_prompt':'Sarah, adult woman, red coat, dark hallway','motion_prompt':'Slow push in','delivery':'quiet and restrained','pause_before':.2,'pause_after':.5}
script={'title':'The key','description':'A key opens a mystery.','hashtags':['#horror'],'summary':'A warm key reveals an intruder.','characters':[{'name':'Sarah','look':'adult woman, red coat'}],'environments':[{'name':'hall','look':'dark hallway'}],'scenes':[scene,dict(scene,narration='Her father stepped out. He had been hiding from the intruder. Sarah called the police, who caught the burglar climbing out of the window. She locked it and led her father safely outside.')], 'plan':plan}
def audit(ok): return {'checks':{k:{'passed':ok,'quotes':['The key was warm.'],'evidence':'Scene 1 establishes the warm key before scene 2 explains it.'} for k in narrative.CHECKS},'issues':[] if ok else [{'severity':'critical','problem':'missing clue','evidence':'scene 2','correction':'plant clue in scene 1'}]}
def external(base,path,data=None,**kw):
 if path=='/api/ps':return {'models':[]}
 if path=='/model/loaded': return {'models':[]}
 if path=='/free':return {}
 if path=='/engines/tts':return {'active':'fixture','backends':[{'id':'fixture','supports_emotion':False}]}
 if path=='/openapi.json':return {'components':{'schemas':{'SpeechRequest':{'properties':{'speed':{},'instructions':{},'language':{}}}}}}
 if path=='/v1/audio/speech':
  assert '[' not in data['input']; assert 'language' in data
  b=io.BytesIO()
  with wave.open(b,'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(44100);w.writeframes(b'\0\0'*44100)
  return b.getvalue(),'audio/wav'
 raise AssertionError(path)
cfg={'niche':'haunted key story','language':'en-US','duration':'30-40','voice_provider':'voicestudio'}
def responses(items):
 items=list(items)
 story=items[1].get('story',items[1])
 draft={k:v for k,v in story.items() if k not in ('scenes','plan')}
 draft['story_text']=' '.join(s['narration'] for s in story['scenes'])
 items.insert(1,draft)
 return [(json.dumps(x),'test') for x in items]
# Roteiro com cenas suficientes para 30-40 s (as travas locais exigem pelo menos 4 cenas)
script4=dict(script,scenes=[dict(scene,narration='The key was warm. Someone had just used it.'),
 dict(scene,narration='Sarah noticed wet footprints leading from the unlocked kitchen window to the hallway, where she heard a familiar cough behind the door.'),
 dict(scene,narration='Her father stepped out. He had been hiding from the intruder.'),
 dict(scene,narration='Sarah called the police, who caught the burglar climbing out of the window. She locked it and led her father safely outside.')])
answers=[plan,script4,audit(False),dict(script4,corrections=['Added warm key clue']),audit(True)]
with patch.object(p,'external',external),patch.object(p,'llm_chat',side_effect=responses(answers)):
 result=p.write_script(cfg,[])
 assert result['review']['approved'] and len(result['review']['history'])==2
 print('PASS planning, drafting, failed review, correction, independent revalidation')
with patch.object(p,'external',external),patch.object(p,'llm_chat',return_value=(json.dumps({}),'test')):
 try:p.write_script(cfg,[]);raise AssertionError('invalid accepted')
 except RuntimeError:print('PASS invalid structured response limited to 3 attempts')
with tempfile.TemporaryDirectory() as folder,patch.object(p,'external',external):
 timing=p.narrate(Path(folder),copy.deepcopy(script['scenes']),cfg,lambda:False)
 assert 3.3<timing['duration']<4 and len(timing['scenes'])==2
 assert timing['scenes'][1]['start']>timing['scenes'][0]['speech_end']
 print('PASS real FFmpeg scene pauses, concatenation, measured duration and timeline',timing['duration'])
v={'id':'fixture','series_id':'fixture','config':cfg,'script':copy.deepcopy(result)}
with patch.object(p,'_upd',side_effect=lambda v,**kw:v.update(kw)):
 p.produce(v)
 assert v['status']=='review' and not v.get('approved')
 print('PASS production stops before voice/images awaiting approval')
print('All targeted checks passed')

# HTTP action contracts: critical gate and separate screen-only CTA.
class Handler:
 def __init__(self,action,body):
  b=json.dumps(body).encode();self.path='/api/videos/abc123/'+action;self.rfile=io.BytesIO(b);self.headers={'Content-Length':str(len(b))};self.result=None
 def send(self,code,data):self.result=(code,data)
v={'id':'abc123','series_id':'fixture','config':dict(cfg),'status':'review','script':copy.deepcopy(script),'title':script['title']}
v['script']['review']=audit(False);v['script']['review']['approved']=False
with patch.object(p,'VIDEOS',{'abc123':v}),patch.object(p,'QUEUE',[]),patch.object(p,'_upd',side_effect=lambda v,**kw:v.update(kw)):
 h=Handler('approve',{});assert p.route(h,'POST');assert h.result[0]==400 and not p.QUEUE
 h=Handler('approve',{'override_critical':True,'cta_enabled':True,'cta_text':'Follow {channel}.','channel':'Key Stories','cta_narrated':False})
 assert p.route(h,'POST');assert h.result[0]==200 and p.QUEUE==['abc123']
 assert v['script']['scenes'][-1]['screen_only'] and v['script']['scenes'][-1]['narration']=='Follow Key Stories.'
 assert len(v['script']['scenes'])==3
 print('PASS HTTP critical error override, approval queue and separate screen-only personalized CTA')

answers=[plan,script,audit(False),script,audit(False),script,audit(False)]
with patch.object(p,'external',external),patch.object(p,'llm_chat',side_effect=responses(answers)):
 result=p.write_script(cfg,[])
 assert not result['review']['approved'] and len(result['review']['history'])==3
 print('PASS unresolved narrative remains rejected after bounded repair attempts')
forged=audit(True)
forged['checks']['resolution']['quotes']=['This ending never appears in the narration.']
answers=[plan,script,forged,forged,forged]
with patch.object(p,'external',external),patch.object(p,'llm_chat',side_effect=responses(answers)):
 result=p.write_script(cfg,[])
 assert not result['review']['approved'] and result['review']['issues'][0]['severity']=='critical'
 assert result['scenes']
 print('PASS review rejects fabricated evidence, retains draft and reports critical failure')
short=copy.deepcopy(script);short['scenes'][-1]['narration']='Sarah was ready to escape.'
answers=[plan,short,audit(True),short,audit(True),short,audit(True)]
with patch.object(p,'external',external),patch.object(p,'llm_chat',side_effect=responses(answers)):
 result=p.write_script(cfg,[])
 assert not result['review']['approved']
 assert any('final anuncia' in i['problem'] for i in result['review']['issues'])
 print('PASS local guards reject pending endings even when the model approves')
with patch.object(p,'CANCEL',{v['id']}):
 try:p.produce(v);raise AssertionError('cancel ignored')
 except InterruptedError: print('PASS cancellation respected before production approval')
answers=[plan,{'story':script4},audit(True)]
with patch.object(p,'external',external),patch.object(p,'llm_chat',side_effect=responses(answers)):
 result=p.write_script(cfg,[])
 assert result['review']['approved']
 print('PASS valid story envelopes are normalized before schema validation')
draft={k:val for k,val in script.items() if k not in ('scenes','plan')}
draft['story_text']=' '.join(s['narration'] for s in script['scenes'])
omitted=copy.deepcopy(script);omitted['scenes'][0]['narration']='The key was warm.'
answers=[plan,draft,omitted,omitted,omitted]
with patch.object(p,'external',external),patch.object(p,'llm_chat',side_effect=[(json.dumps(x),'test') for x in answers]):
 try:p.write_script(cfg,[]);raise AssertionError('storyboard omitted words')
 except RuntimeError:print('PASS storyboard cannot rewrite or omit the canonical spoken story')
