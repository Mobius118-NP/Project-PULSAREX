'use strict';
const $ = id => document.getElementById(id);
const state = {config:null, frame:null, socket:null, sequence:-1, spectra:[], events:[], reconnect:null, connected:false, view:'monitor'};
const palette = {grid:'#1a2a34', text:'#67818f', green:'#5ee3aa', amber:'#d5b879'};
const number = (value, decimals=0) => Number.isFinite(value) ? value.toLocaleString(undefined, {maximumFractionDigits:decimals, minimumFractionDigits:decimals}) : '—';
let toastTimer;
function toast(message, error=false) {
  const node = $('toast'); node.textContent = message; node.classList.remove('hidden');
  node.style.borderColor = error ? '#ab6f56' : ''; clearTimeout(toastTimer);
  toastTimer = setTimeout(() => node.classList.add('hidden'), 5000);
}
async function api(path, method='GET', body) {
  const response = await fetch('/api/' + path, {method, headers:body === undefined ? {} : {'Content-Type':'application/json'}, body:body === undefined ? undefined : JSON.stringify(body)});
  const result = await response.json();
  if (!response.ok) {
    if (response.status === 401 && !$('login-dialog').open) $('login-dialog').showModal();
    throw new Error(typeof result.detail === 'string' ? result.detail : 'Request failed. Check your input.');
  }
  return result;
}
function applyConfig(config) {
  state.config = config;
  $('reference-hz').value = config.reference_hz; $('shift-range').value = config.shift_range_hz;
  $('reference-hz').max = config.sample_rate / 2 - 1;
  $('negative-range').textContent = '−' + number(config.shift_range_hz);
  $('positive-range').textContent = '+' + number(config.shift_range_hz);
  $('threshold').value = config.event_threshold_db; $('threshold-label').textContent = config.event_threshold_db + ' dB';
  $('adapt-baseline').checked = config.baseline_adaptation;
  const neutral = Math.min(49, config.zero_tolerance_hz / config.shift_range_hz * 50);
  $('gradient-track').style.background = `linear-gradient(90deg,#9256f4 0%,#4195f2 ${25-neutral/2}%,#42dc97 ${50-neutral}%,#42dc97 ${50+neutral}%,#f7d056 ${75+neutral/2}%,#f6535b 100%)`;
}
async function configure(changes) {
  const config = await api('config','PATCH',changes); applyConfig(config);
  state.spectra.length = 0; state.sequence = -1; state.frame = null;
  toast('Configuration applied. Analysis pipeline restarted.');
}
function connect() {
  if (state.socket) { state.socket.onclose = null; state.socket.close(); }
  const socket = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/ws`);
  state.socket = socket;
  socket.onopen = () => { state.connected=true; $('connection-light').classList.remove('offline'); $('connection-label').textContent='CONNECTED'; };
  socket.onmessage = event => {
    try { render(JSON.parse(event.data)); } catch (error) { console.error('Measurement render failed',error); }
  };
  socket.onerror = () => { $('connection-label').textContent='RECONNECTING'; };
  socket.onclose = () => {
    state.connected=false; $('connection-light').classList.add('offline'); $('connection-label').textContent='DISCONNECTED';
    clearTimeout(state.reconnect); state.reconnect=setTimeout(async () => {
      try { const session=await api('session'); if (session.authenticated) connect(); else if (!$('login-dialog').open) $('login-dialog').showModal(); }
      catch { connect(); }
    },2000);
  };
}
function render(frame) {
  const status=frame.status || {}, simulation=status.source === 'simulation';
  const paused=!status.running, error=status.error;
  $('source-badge').textContent=simulation?'SIMULATION':'LIVE MICROPHONE';
  $('demo-notice').classList.toggle('hidden',!simulation);
  $('capture-button').textContent=paused?'Start acquisition':'Pause acquisition';
  $('calibrate-button').disabled=paused || !!error;
  $('error-banner').classList.toggle('hidden',!error); $('error-banner').textContent=error || '';
  $('system-source').textContent=simulation?'SIMULATION':'MICROPHONE';
  $('sample-rate').textContent=number(status.sample_rate)+' Hz'; $('channels').textContent=status.channels;
  $('mic-state').textContent=status.microphone_active?'CAPTURING':simulation?'INACTIVE':error?'UNAVAILABLE':paused?'STOPPED':'CONNECTING';
  $('clients').textContent=status.clients; $('buffer-detail').textContent=`${status.overruns || 0} BUFFER OVERRUNS · ${paused?'PAUSED':'BOUNDED QUEUE'}`;
  $('health').textContent=error?'ERROR':paused?'PAUSED':'NOMINAL';
  $('fft-detail').textContent=`HANN WINDOW · ${number(status.fft_size)} SAMPLES · HOP ${number(status.hop_size)}`;
  const baseline=frame.baseline || {};
  $('baseline-status').textContent=baseline.calibrating?'CALIBRATING':baseline.ready?'CALIBRATED':'UNCALIBRATED';
  $('baseline-heading').textContent=baseline.calibrating?'Learning the environment…':baseline.ready?'Your reference is set.':'Learn the room.';
  $('baseline-description').textContent=baseline.calibrating?`${Math.round(baseline.progress*100)}% complete. Keep the environment representative and quiet.`:baseline.ready?'Changes are compared against the calibrated spectral profile. Quiet frames adapt only when enabled.':'Calibrate a quiet interval to detect spectral changes against your environment.';
  $('calibration-progress').style.width=(baseline.progress || 0)*100+'%';
  $('calibrate-button').textContent=baseline.calibrating?'↻ Recalibrate baseline':'↻ Calibrate baseline';
  if (!frame.spectrum_dbfs) { state.frame=frame; drawAll(); return; }
  state.frame=frame;
  if (frame.sequence !== state.sequence) {
    state.sequence=frame.sequence;
    state.spectra.push(frame.spectrum_dbfs); if (state.spectra.length>180) state.spectra.shift();
  }
  $('rms').textContent=number(frame.rms_dbfs,1); $('dominant').textContent=number(frame.peaks?.[0]?.hz,1);
  $('peak-detail').textContent=frame.peaks?.length?`${frame.peaks.length} PEAKS · ${number(frame.peaks[0].snr_db,1)} dB ABOVE FLOOR`:'No reliable spectral peaks';
  $('centroid').textContent=number(frame.centroid_hz); $('latency').textContent=number(frame.processing_ms,1);
  $('noise-detail').textContent=`NOISE FLOOR ${number(frame.noise_floor_dbfs,1)} dBFS`;
  $('spectrogram-detail').textContent=`${state.spectra.length} FRAMES / 180 MAX`;
  $('spectrogram-span').textContent=`~${number(state.spectra.length / (state.config?.update_hz || 12),1)} s HISTORY`;
  $('frame-number').textContent=`FRAME ${String(frame.sequence).padStart(6,'0')}`;
  const shift=frame.shift, valid=shift?.reliable;
  $('shift-value').textContent=valid?(shift.hz>=0?'+':'−')+number(Math.abs(shift.hz),1):'—';
  $('shift-value').style.color=shift.color; $('shift-status').textContent=valid?'VALID ESTIMATE':shift.status.toUpperCase();
  $('shift-description').textContent=simulation?'Controlled synthetic frequency shift':'Spectrum shift · motion unconfirmed';
  $('observed-detail').textContent=`OBSERVED ${number(shift.observed_hz,1)} Hz`;
  $('shift-marker').classList.toggle('hidden',!valid);
  if (valid) $('shift-marker').style.left=(50+Math.max(-1,Math.min(1,shift.hz/(state.config?.shift_range_hz || 200)))*50)+'%';
  const direction=frame.direction || {};
  $('bearing-overlay').classList.toggle('hidden',!!direction.available);
  $('bearing-mode').textContent=direction.simulated?'SIMULATED':direction.available?'EXPERIMENTAL':'UNAVAILABLE';
  $('bearing-value').replaceChildren(document.createTextNode(direction.available?number(direction.bearing_deg,1):'—'),unit('°'));
  $('bearing-confidence').replaceChildren(document.createTextNode(direction.available?number(direction.confidence*100):'—'),unit('%'));
  $('bearing-uncertainty').replaceChildren(document.createTextNode(direction.available?'±'+number(direction.uncertainty_deg):'—'),unit('°'));
  $('bearing-note').textContent=direction.simulated?'Synthetic bearing · demonstration only':direction.available?'Experimental far-field array estimate':direction.reason || 'Synchronized calibrated array required';
  const harmonics=$('harmonics'); harmonics.replaceChildren();
  if (!frame.harmonics?.length) { const p=document.createElement('p'); p.textContent='No confident harmonic grouping. Signals may be nonharmonic or ambiguous.'; harmonics.append(p); }
  for (const group of frame.harmonics || []) {
    const row=document.createElement('div'); row.className='harmonic';
    const left=document.createElement('div'), strong=document.createElement('strong'), small=document.createElement('small'), score=document.createElement('span');
    strong.textContent=number(group.fundamental_hz,1)+' Hz'; small.textContent=`${group.members.length} COMPONENTS · ${group.stability?'CONSISTENT':'NEW CANDIDATE'}`;
    score.textContent=number(group.confidence*100)+'%'; left.append(strong,small); row.append(left,score); harmonics.append(row);
  }
  drawAll();
}
function unit(text) { const node=document.createElement('em'); node.textContent=text; return node; }
function chart(id) {
  const canvas=$(id), rect=canvas.getBoundingClientRect(), ratio=Math.min(devicePixelRatio || 1,2);
  if (!rect.width || !rect.height) return null;
  const width=Math.round(rect.width*ratio), height=Math.round(rect.height*ratio);
  if (canvas.width!==width || canvas.height!==height) { canvas.width=width; canvas.height=height; }
  const ctx=canvas.getContext('2d'); ctx.setTransform(ratio,0,0,ratio,0,0); ctx.clearRect(0,0,rect.width,rect.height);
  ctx.font='9px Consolas,monospace'; return {ctx,w:rect.width,h:rect.height};
}
function grid(ctx,w,h,left=42,right=14,top=26,bottom=28) {
  const area={x:left,y:top,w:w-left-right,h:h-top-bottom};
  ctx.strokeStyle=palette.grid; ctx.lineWidth=1; ctx.fillStyle=palette.text;
  for (let i=0;i<=5;i++) { const y=top+area.h*i/5; ctx.beginPath();ctx.moveTo(left,y);ctx.lineTo(w-right,y);ctx.stroke();ctx.textAlign='right';ctx.fillText(String(-i*20),left-9,y+3); }
  return area;
}
function spectrum() {
  const chartData=chart('spectrum'); if (!chartData) return;
  const {ctx,w,h}=chartData,a=grid(ctx,w,h),frame=state.frame;
  const cfg=state.config || {min_frequency:30,max_frequency:18000};
  const xFor=f=>a.x+(Math.log(f/cfg.min_frequency)/Math.log(cfg.max_frequency/cfg.min_frequency))*a.w;
  ctx.fillStyle=palette.text;ctx.textAlign='center';
  for (const f of [30,60,100,200,500,1000,2000,5000,10000,18000]) {
    if (f<cfg.min_frequency || f>cfg.max_frequency) continue;
    const x=xFor(f);ctx.strokeStyle=palette.grid;ctx.beginPath();ctx.moveTo(x,a.y);ctx.lineTo(x,a.y+a.h);ctx.stroke();ctx.fillText(f>=1000?(f/1000)+'k':String(f),x,h-10);
  }
  if (!frame?.spectrum_dbfs) { ctx.textAlign='center';ctx.fillText('WAITING FOR ACQUISITION',w/2,h/2);return; }
  const frequencies=frame.frequencies,values=frame.spectrum_dbfs;
  const yFor=db=>a.y+Math.max(0,Math.min(1,-db/100))*a.h;
  ctx.save();ctx.beginPath();ctx.rect(a.x,a.y,a.w,a.h);ctx.clip();
  if (frame.baseline?.mean_dbfs) {
    ctx.strokeStyle=palette.amber;ctx.lineWidth=1;ctx.setLineDash([3,4]);ctx.beginPath();
    frame.baseline.mean_dbfs.forEach((v,i)=>{const x=xFor(frequencies[i]),y=yFor(v);i?ctx.lineTo(x,y):ctx.moveTo(x,y);});ctx.stroke();ctx.setLineDash([]);
  }
  const gradient=ctx.createLinearGradient(0,a.y,0,a.y+a.h);gradient.addColorStop(0,'#5ee3aa45');gradient.addColorStop(1,'#5ee3aa00');
  ctx.beginPath();ctx.moveTo(xFor(frequencies[0]),a.y+a.h);values.forEach((v,i)=>ctx.lineTo(xFor(frequencies[i]),yFor(v)));ctx.lineTo(xFor(frequencies.at(-1)),a.y+a.h);ctx.closePath();ctx.fillStyle=gradient;ctx.fill();
  ctx.beginPath();values.forEach((v,i)=>{const x=xFor(frequencies[i]),y=yFor(v);i?ctx.lineTo(x,y):ctx.moveTo(x,y);});ctx.strokeStyle=palette.green;ctx.lineWidth=1.4;ctx.stroke();
  ctx.fillStyle=palette.green;
  for (const peak of frame.peaks.slice(0,4)) { const x=xFor(peak.hz),y=yFor(peak.dbfs);ctx.beginPath();ctx.arc(x,y,2.5,0,Math.PI*2);ctx.fill();ctx.textAlign='center';ctx.fillText(number(peak.hz)+' Hz',x,Math.max(a.y+10,y-10)); }
  ctx.restore();
}
const heatStops=[[12,23,35],[17,49,73],[21,105,128],[47,177,147],[229,210,122],[249,239,202]];
function heat(value) {
  const v=Math.max(0,Math.min(.99999,(value+100)/90))*(heatStops.length-1),i=Math.floor(v),t=v-i;
  return heatStops[i].map((c,j)=>Math.round(c+(heatStops[i+1][j]-c)*t));
}
const heatCanvas=document.createElement('canvas');
function spectrogram() {
  const chartData=chart('spectrogram'); if (!chartData) return;
  const {ctx,w,h}=chartData,left=42,bottom=25,rows=180,bins=state.config?.display_bins || 384;
  heatCanvas.width=bins;heatCanvas.height=rows;
  const hc=heatCanvas.getContext('2d'),data=hc.createImageData(bins,rows);
  for(let y=0;y<rows;y++) for(let x=0;x<bins;x++) {
    const sourceRow=state.spectra[y-(rows-state.spectra.length)],rgb=sourceRow?heat(sourceRow[x]):heat(-140),offset=(y*bins+x)*4;
    data.data[offset]=rgb[0];data.data[offset+1]=rgb[1];data.data[offset+2]=rgb[2];data.data[offset+3]=255;
  }
  hc.putImageData(data,0,0);ctx.imageSmoothingEnabled=false;ctx.drawImage(heatCanvas,left,0,w-left-14,h-bottom);
  ctx.fillStyle=palette.text;ctx.textAlign='right';ctx.fillText('PAST',left-8,12);ctx.fillText('NOW',left-8,h-bottom-4);
  ctx.textAlign='center';const cfg=state.config || {min_frequency:30,max_frequency:18000};
  for(const f of [30,100,500,1000,5000,18000]) if(f>=cfg.min_frequency && f<=cfg.max_frequency) { const x=left+Math.log(f/cfg.min_frequency)/Math.log(cfg.max_frequency/cfg.min_frequency)*(w-left-14);ctx.fillText(f>=1000?f/1000+'k':f,x,h-8); }
}
function polar() {
  const chartData=chart('polar'); if(!chartData) return;
  const {ctx,w,h}=chartData,x=w/2,y=h/2+3,r=Math.min(w,h)/2-28;
  ctx.strokeStyle=palette.grid;ctx.lineWidth=1;
  for(const fraction of [.25,.5,.75,1]){ctx.beginPath();ctx.arc(x,y,r*fraction,0,Math.PI*2);ctx.stroke();}
  for(let angle=0;angle<360;angle+=30){const a=(angle-90)*Math.PI/180;ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(x+Math.cos(a)*r,y+Math.sin(a)*r);ctx.stroke();}
  ctx.fillStyle=palette.text;ctx.textAlign='center';ctx.fillText('000° N',x,y-r-12);ctx.fillText('180°',x,y+r+16);ctx.fillText('270°',x-r-13,y+3);ctx.fillText('090°',x+r+13,y+3);
  const direction=state.frame?.direction;if(!direction?.available)return;
  const a=(direction.bearing_deg-90)*Math.PI/180,u=(direction.uncertainty_deg || 12)*Math.PI/180;
  ctx.beginPath();ctx.moveTo(x,y);ctx.arc(x,y,r,a-u,a+u);ctx.closePath();ctx.fillStyle='#5ee3aa18';ctx.fill();
  ctx.strokeStyle='#5ee3aa70';ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(x+Math.cos(a)*r,y+Math.sin(a)*r);ctx.stroke();
  const history=state.frame?.bearing_history || [];
  history.slice(-35).forEach((point,i)=>{const p=(point.bearing_deg-90)*Math.PI/180;ctx.fillStyle=`rgba(94,227,170,${.08+i/50})`;ctx.beginPath();ctx.arc(x+Math.cos(p)*r*.72,y+Math.sin(p)*r*.72,1.8,0,Math.PI*2);ctx.fill();});
  ctx.fillStyle=palette.green;ctx.shadowColor=palette.green;ctx.shadowBlur=12;ctx.beginPath();ctx.arc(x+Math.cos(a)*r*.72,y+Math.sin(a)*r*.72,4,0,Math.PI*2);ctx.fill();ctx.shadowBlur=0;
}
function shiftHistory() {
  const chartData=chart('shift-history'); if(!chartData)return;
  const {ctx,w,h}=chartData;ctx.strokeStyle=palette.grid;ctx.setLineDash([2,4]);ctx.beginPath();ctx.moveTo(0,h/2);ctx.lineTo(w,h/2);ctx.stroke();ctx.setLineDash([]);
  const history=(state.frame?.shift_history || []).slice(-120),range=state.config?.shift_range_hz || 200;
  ctx.lineWidth=1.4;
  for(let i=1;i<history.length;i++) if(history[i].reliable && history[i-1].reliable) {
    ctx.strokeStyle=history[i].color;ctx.beginPath();ctx.moveTo((i-1)/119*w,h/2-Math.max(-1,Math.min(1,history[i-1].hz/range))*(h/2-4));ctx.lineTo(i/119*w,h/2-Math.max(-1,Math.min(1,history[i].hz/range))*(h/2-4));ctx.stroke();
  }
}
function drawAll(){if(state.view==='monitor'){spectrum();spectrogram();polar();shiftHistory();}}
function eventRows(events,node,archive=false) {
  node.replaceChildren();
  for(const event of events) {
    const row=document.createElement('tr'),date=new Date(event.timestamp);
    const cells=[archive?date.toLocaleString():date.toLocaleTimeString(),event.category,event.band_hz.length?event.band_hz.map(v=>number(v)).join('–')+' Hz':'—','+'+number(event.change_db,1)+' dB'];
    if(archive)cells.push(number(event.duration_seconds,2)+' s');cells.push(number(event.score*100)+'%');if(archive)cells.push(event.source);
    cells.forEach((value,i)=>{const cell=document.createElement('td');cell.textContent=value;if(i===3)cell.className='change';row.append(cell);});
    node.append(row);
  }
}
async function refreshEvents() {
  if(!state.config)return;
  try{
    const result=await api('events?limit=5000');state.events=result.events;$('event-count').textContent=state.events.length;
    eventRows(state.events.slice(0,5),$('recent-events'));$('events-empty').classList.toggle('hidden',!!state.events.length);renderArchive();
  }catch(error){console.warn('Event update',error.message);}
}
function renderArchive(){const filter=$('event-filter').value,events=state.events.filter(e=>!filter || e.category===filter);eventRows(events,$('archive-events'),true);$('archive-empty').classList.toggle('hidden',!!events.length);}
function view(name){state.view=name;$('monitor-view').classList.toggle('hidden',name!=='monitor');$('archive-view').classList.toggle('hidden',name!=='events');document.querySelectorAll('[data-view]').forEach(button=>button.classList.toggle('active',button.dataset.view===name));drawAll();}
async function openSettings(){
  const c=state.config;if(!c)return;
  $('setting-source').value=c.source;$('setting-rate').value=c.sample_rate;$('setting-fft').value=c.fft_size;$('setting-tolerance').value=c.zero_tolerance_hz;$('setting-calibration').value=c.calibration_seconds;$('setting-harmonics').checked=c.harmonics_enabled;
  $('settings-dialog').showModal();$('device-note').textContent='Checking input devices…';
  try{const result=await api('devices'),select=$('setting-device');select.replaceChildren(new Option('System default input',''));for(const d of result.devices)select.append(new Option(`${d.name} · ${d.backend || 'audio'} · ${d.default_sample_rate} Hz`,String(d.id)));select.value=c.device ?? '';$('device-note').textContent=result.error || `${result.devices.length} inputs found. On Windows, prefer WASAPI at its listed native rate. Current channels: ${c.channels}.`;}
  catch(error){$('device-note').textContent=error.message;}
}
function bind(id,event,fn){$(id).addEventListener(event,async e=>{try{await fn(e);}catch(error){toast(error.message,true);}});}
document.querySelectorAll('[data-view]').forEach(button=>button.addEventListener('click',()=>view(button.dataset.view)));
bind('capture-button','click',async()=>{const action=state.frame?.status.running?'stop':'start';await api('capture/'+action,'POST');render(await api('measurements'));toast(action==='stop'?'Acquisition paused. Microphone stream closed.':'Acquisition started.');});
bind('calibrate-button','click',async()=>{await api('baseline/calibrate','POST');toast('Baseline calibration started. Keep the environment quiet.');});
bind('use-microphone','click',()=>openSettings().then(()=>{$('setting-source').value='microphone';}));
bind('apply-reference','click',()=>configure({reference_hz:Number($('reference-hz').value),shift_range_hz:Number($('shift-range').value)}));
$('threshold').addEventListener('input',()=>{$('threshold-label').textContent=$('threshold').value+' dB';});
bind('threshold','change',async()=>{try{await configure({event_threshold_db:Number($('threshold').value)});}catch(error){applyConfig(state.config);throw error;}});
bind('adapt-baseline','change',async()=>{try{await configure({baseline_adaptation:$('adapt-baseline').checked});}catch(error){applyConfig(state.config);throw error;}});
bind('settings-button','click',openSettings);bind('close-settings','click',()=>$('settings-dialog').close());bind('cancel-settings','click',()=>$('settings-dialog').close());
bind('settings-form','submit',async e=>{e.preventDefault();const rate=Number($('setting-rate').value);await configure({source:$('setting-source').value,device:$('setting-device').value===''?null:Number($('setting-device').value),sample_rate:rate,fft_size:Number($('setting-fft').value),zero_tolerance_hz:Number($('setting-tolerance').value),calibration_seconds:Number($('setting-calibration').value),harmonics_enabled:$('setting-harmonics').checked});$('settings-dialog').close();});
bind('show-archive','click',()=>view('events'));bind('event-filter','change',renderArchive);
$('login-dialog').addEventListener('cancel',e=>e.preventDefault());
bind('login-form','submit',async e=>{e.preventDefault();try{await api('login','POST',{token:$('access-token').value});$('access-token').value='';$('login-error').textContent='';$('login-dialog').close();await initialize();}catch(error){$('login-error').textContent=error.message;}});
window.addEventListener('resize',drawAll);
setInterval(()=>{$('clock').textContent=new Date().toLocaleTimeString('en-GB')+' LOCAL';},1000);
setInterval(refreshEvents,2000);
async function initialize(){try{const session=await api('session');if(!session.authenticated){$('login-dialog').showModal();return;}applyConfig(await api('config'));render(await api('measurements'));await refreshEvents();connect();}catch(error){$('error-banner').textContent='Cannot connect to PULSAR: '+error.message;$('error-banner').classList.remove('hidden');}}
initialize();
