const fs=require('fs'),vm=require('vm'),assert=require('assert');
const src=fs.readFileSync(require('path').join(__dirname,'../static/index.html'),'utf8');
const fn=src.slice(src.indexOf('function narrativePanel('),src.indexOf('async function narrativeAction('));
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
for(const status of ['review','done','error','cancelled']) {
const v={id:'abc123',status,scenes:[{narration:'<script> & story'}],narrative:{plan:{revelation:'clue',ending:'resolved'},review:{approved:false,issues:[],history:[]},summary:'test',timing:{duration:3.7,wpm:115,style_supported:false}},voice_preview_url:'/api/voice-preview',audio_url:'/media/test.wav',narration_config:{speed:.8,pause_intensity:0,manual_speed:true,narration_profile:'horror'},cta:{enabled:true,text:'Follow "Key"',gap:1,narrated:false}};
const html=vm.runInNewContext(fn+';narrativePanel(v)',{v,esc,JSON});
assert(html.includes('Aprovar e produzir'));assert(html.includes('&lt;script&gt;'));assert(html.includes('value="0.8"'));assert(html.includes('Follow &quot;Key&quot;'));assert(!html.includes('undefined'));
console.log('PASS panel rendering',status);
}
