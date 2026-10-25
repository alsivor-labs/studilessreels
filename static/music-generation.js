/* Instrumental music generation; shares the existing library and series draft. */
const MUSIC_UI = {
  draft: {preset:'horror', title:'Trilha de terror', prompt:'Dark cinematic horror underscore, sparse low piano, ominous sustained strings, unsettling ambient drones, slow rising tension, restrained percussion, background soundtrack for spoken narration', seconds:40, bpm:60, seed:''},
  presets:{}, available:false, timer:null, epoch:0, jobs:[], completed:new Set()
};
function musicGeneratorPanel(wizard=false) {
  const d=MUSIC_UI.draft;
  return `<section class="box" style="margin-bottom:22px" id="musicGenerator" data-wizard="${wizard}">
    <h3 style="margin:0 0 8px">Criar trilha instrumental</h3>
    <p class="muted">Gere uma música sem voz para acompanhar a narração. Ao terminar, ela ficará disponível na sua biblioteca.</p>
    <div id="musicGenAvailability" class="muted" role="status">Conferindo gerador de música...</div>
    <div class="field"><label class="label" for="mg-preset">Clima</label><select class="select" id="mg-preset" onchange="setMusicPreset(this.value)">
      ${[['horror','Terror'],['suspense','Suspense'],['mystery','Mistério'],['emotional','Emocional'],['custom','Personalizado']].map(([id,name])=>`<option value="${id}" ${d.preset===id?'selected':''}>${name}</option>`).join('')}</select></div>
    <div class="field"><label class="label" for="mg-title">Nome da trilha</label><input class="input" id="mg-title" maxlength="100" value="${esc(d.title)}" oninput="MUSIC_UI.draft.title=this.value"></div>
    <div class="field"><label class="label" for="mg-prompt">Descrição musical</label><textarea class="textarea" rows="4" id="mg-prompt" maxlength="3000" oninput="MUSIC_UI.draft.prompt=this.value">${esc(d.prompt)}</textarea><div class="help">Descreva o clima e os instrumentos. Os presets já incluem sugestões.</div></div>
    <div style="display:flex;gap:16px;flex-wrap:wrap"><div class="field" style="flex:1;min-width:160px"><label class="label" for="mg-seconds">Duração desejada (segundos)</label><input class="input" id="mg-seconds" type="number" min="10" max="180" step="1" value="${esc(d.seconds)}" oninput="MUSIC_UI.draft.seconds=this.value"></div>
    <div class="field" style="flex:1;min-width:160px"><label class="label" for="mg-bpm">Andamento (BPM)</label><input class="input" id="mg-bpm" type="number" min="30" max="200" step="1" value="${esc(d.bpm)}" oninput="MUSIC_UI.draft.bpm=this.value"></div></div>
    <details><summary>Variação opcional</summary><div class="field"><label for="mg-seed">Número da variação — deixe vazio para sortear</label><input class="input" id="mg-seed" type="number" min="0" max="4294967295" step="1" value="${esc(d.seed)}" oninput="MUSIC_UI.draft.seed=this.value"></div></details>
    <div style="margin-top:16px"><button class="btn" id="musicGenSubmit" disabled onclick="submitMusicGeneration()">${ic('music')}Gerar instrumental</button></div>
    <div class="help" style="margin-top:10px">A duração real será medida após gerar. A produção aguarda sua vez quando a GPU está ocupada.</div>
    <div id="musicGenJobs" style="margin-top:18px" aria-live="polite"></div>
  </section>`;
}
function setMusicPreset(value) {
  const preset=MUSIC_UI.presets[value];
  MUSIC_UI.draft.preset=value;
  if (preset) {
    MUSIC_UI.draft.prompt=preset.prompt;
    MUSIC_UI.draft.bpm=preset.bpm;
    if (!MUSIC_UI.draft.title || MUSIC_UI.draft.title.startsWith('Trilha de ')) MUSIC_UI.draft.title='Trilha de '+preset.name.toLowerCase();
    document.getElementById('mg-prompt').value=MUSIC_UI.draft.prompt;
    document.getElementById('mg-bpm').value=MUSIC_UI.draft.bpm;
    document.getElementById('mg-title').value=MUSIC_UI.draft.title;
  }
}
async function initMusicGenerator() {
  const panel=document.getElementById('musicGenerator'); if (!panel) return;
  try {
    const info=await api('/api/music/generation/status');
    if (!panel.isConnected) return;
    MUSIC_UI.presets=info.presets||{}; MUSIC_UI.available=!!info.available;
    document.getElementById('musicGenAvailability').textContent=info.available?'Gerador pronto · somente instrumental':(info.error||'Gerador indisponível. Confira o ComfyUI.');
    document.getElementById('musicGenSubmit').disabled=!info.available;
  } catch(e) {
    if (panel.isConnected) document.getElementById('musicGenAvailability').textContent=e.message;
  }
  if (panel.isConnected) pollMusicGenerations();
}
async function submitMusicGeneration(data) {
  const button=document.getElementById('musicGenSubmit'); if (button) button.disabled=true;
  try {
    await api('/api/music/generation',{json:data||{...MUSIC_UI.draft}});
    toast('Trilha adicionada à fila.');
    pollMusicGenerations();
  } catch(e) {toast(e.message);}
  finally {if(button?.isConnected) button.disabled=!MUSIC_UI.available;}
}
async function cancelMusicGeneration(id) {
  try {await api(`/api/music/generation/${id}/cancel`,{json:{}});pollMusicGenerations();} catch(e) {toast(e.message);}
}
function retryMusicGeneration(id) {
  const job=MUSIC_UI.jobs.find(j=>j.id===id); if (!job) return;
  submitMusicGeneration(Object.fromEntries(['title','prompt','preset','seconds','bpm','seed'].map(k=>[k,job[k]])));
}
function selectGeneratedMusic(file) {
  if (!D.music.includes(file)) D.music.push(file);
  S.music=null; S.musicTab='library'; saveDraft(); drawWizard();
  toast('Trilha selecionada para a série.');
}
function musicGenerationCard(job,wizard) {
  const label={queued:'Na fila',waiting:'Aguardando GPU',running:'Gerando instrumental',cancelling:'Cancelando',cancelled:'Cancelada',done:'Pronta',error:'Erro'}[job.status]||job.status;
  const active=['queued','waiting','running','cancelling'].includes(job.status);
  return `<div class="box" style="margin:8px 0"><b>${esc(job.title)}</b> · ${esc(label)}
    <div class="muted">${esc(job.detail||'')} · ${esc(job.seconds)} s solicitados · ${esc(job.bpm)} BPM</div>
    ${job.error?`<div class="err">${esc(job.error)}</div>`:''}
    ${job.status==='done'&&job.url?`<div>${Number(job.duration).toFixed(1)} s reais · variação ${esc(job.seed)}</div><audio controls preload="none" src="${esc(job.url)}" style="width:100%;margin-top:8px"></audio>${wizard?`<button class="btn sm" onclick="selectGeneratedMusic(${esc(JSON.stringify(job.file))})">Usar nesta série</button>`:'<div class="muted">Disponível na biblioteca abaixo e na criação de séries.</div>'}`:''}
    ${active&&job.status!=='cancelling'?`<button class="btn sm ghost" onclick="cancelMusicGeneration(${esc(JSON.stringify(job.id))})">Cancelar</button>`:''}
    ${['error','cancelled'].includes(job.status)?`<button class="btn sm ghost" onclick="retryMusicGeneration(${esc(JSON.stringify(job.id))})">Tentar novamente</button>`:''}</div>`;
}
function pollMusicGenerations() {
  clearTimeout(MUSIC_UI.timer);
  const epoch=++MUSIC_UI.epoch;
  const panel=document.getElementById('musicGenerator'); if (!panel) return;
  const container=panel.querySelector('#musicGenJobs');
  const tick=async()=>{
    if (!panel.isConnected||MUSIC_UI.epoch!==epoch) return;
    try {
      const jobs=await api('/api/music/generation');
      if (!panel.isConnected||MUSIC_UI.epoch!==epoch) return;
      MUSIC_UI.jobs=jobs;
      let added=false;
      jobs.forEach((job,index)=>{
        let row=[...container.children].find(el=>el.dataset.jobId===job.id);
        if (!row) {row=document.createElement('div');row.dataset.jobId=job.id;container.insertBefore(row,container.children[index]||null);}
        const signature=JSON.stringify(job);
        if (row.dataset.signature!==signature) {row.innerHTML=musicGenerationCard(job,panel.dataset.wizard==='true');row.dataset.signature=signature;}
        if (job.status==='done'&&!MUSIC_UI.completed.has(job.id)) {MUSIC_UI.completed.add(job.id);added=true;}
      });
      [...container.children].filter(el=>!jobs.some(j=>j.id===el.dataset.jobId)).forEach(el=>el.remove());
      if (added) {S.music=null;if(document.getElementById('lib')) await drawLib();}
      if(jobs.some(j=>['queued','waiting','running','cancelling'].includes(j.status))) MUSIC_UI.timer=setTimeout(tick,2500);
    } catch(e) {
      if (panel.isConnected&&MUSIC_UI.epoch===epoch) {
        container.textContent='Não foi possível acompanhar a geração: '+e.message;
        MUSIC_UI.timer=setTimeout(tick,5000);
      }
    }
  };
  tick();
}
