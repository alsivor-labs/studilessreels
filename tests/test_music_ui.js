const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let redraws=0,saves=0;
const fields=Object.fromEntries(['mg-prompt','mg-bpm','mg-title'].map(id=>[id,{value:''}]));
const context=vm.createContext({esc,ic:()=>'',D:{music:[]},S:{music:[],musicTab:'generate'},saveDraft:()=>saves++,drawWizard:()=>redraws++,toast:()=>{},document:{getElementById:id=>fields[id]}});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/music-generation.js'),'utf8'),context);
for(const wizard of [true,false]) {
 const html=vm.runInContext(`musicGeneratorPanel(${wizard})`,context);
 assert(html.includes('Gerar instrumental'));assert(html.includes('mg-seconds'));assert(html.includes('mg-bpm'));assert(html.includes('disabled'));assert(!html.includes('undefined'));
}
for(const status of ['queued','waiting','running','cancelling','cancelled','done','error']) {
 context.job={id:'abc123abc123',title:'<script> "Music"',status,seconds:20,bpm:60,duration:20,url:'/media/music/a.mp3',file:'a.mp3',error:status==='error'?'<unsafe>':null,seed:42};
 const html=vm.runInContext('musicGenerationCard(job,true)',context);
 assert(html.includes('&lt;script&gt;'));assert(!html.includes('<unsafe>'));
 if(status==='done') {assert(html.includes('Usar nesta série'));assert(html.includes('<audio'));}
 if(status==='cancelling') assert(!html.includes('cancelMusicGeneration('));
}
vm.runInContext("MUSIC_UI.presets.suspense={name:'Suspense',prompt:'Tense strings',bpm:80};setMusicPreset('suspense')",context);
assert.strictEqual(fields['mg-bpm'].value,80);assert.strictEqual(fields['mg-prompt'].value,'Tense strings');
vm.runInContext("selectGeneratedMusic('a.mp3');selectGeneratedMusic('a.mp3')",context);
assert.strictEqual(context.D.music.length,1);assert.strictEqual(context.S.musicTab,'library');assert.strictEqual(redraws,2);assert.strictEqual(saves,2);
console.log('PASS music panels, all job states, escaping, presets and series selection');
