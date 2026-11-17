'use strict';
const $ = id => document.getElementById(id);
const state = {config:null, frame:null, socket:null, sequence:-1, streamId:null, configRevision:-1, spectra:[], spectraTimes:[], events:[], archiveEvents:[], archiveLimit:200, archiveNewest:null, reconnect:null, connected:false, linkLost:false, lastReceived:0, view:'monitor'};
const palette = {grid:'#29392c', text:'#9aaa8b', green:'#c1d98d', amber:'#d5b879'};
const number = (value, decimals=0) => Number.isFinite(value) ? value.toLocaleString(undefined, {maximumFractionDigits:decimals, minimumFractionDigits:decimals}) : '—';
let inputInventory=null,recoveryLoading=false,recoveryVisible=false;
let toastTimer;
function toast(message, error=false) {
  const node = $('toast'); node.textContent = message; node.classList.remove('hidden');
  node.style.borderColor = error ? '#ab6f56' : ''; clearTimeout(toastTimer);
  toastTimer = setTimeout(() => node.classList.add('hidden'), 5000);
}
async function api(path, method='GET', body) {
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),10000);
  try{
    const response = await fetch('/api/' + path, {method, signal:controller.signal, headers:body === undefined ? {} : {'Content-Type':'application/json'}, body:body === undefined ? undefined : JSON.stringify(body)});
    const result = await response.json();
    if (!response.ok) {
      if (response.status === 401 && !$('login-dialog').open) $('login-dialog').showModal();
      throw new Error(typeof result.detail === 'string' ? result.detail : 'Request failed. Check your input.');
    }
    return result;
  }catch(error){if(error.name==='AbortError')throw new Error('Station request timed out. Retry or select another input.');throw error;}
  finally{clearTimeout(timer);}
}
function deviceOptions(select,inventory,value){
  const automatic=inventory.default_input,option=new Option(automatic?`Automatic: ${automatic.name} / ${automatic.backend} / ${automatic.default_sample_rate} Hz`:'Automatic input','');
  if(automatic){option.dataset.rate=automatic.default_sample_rate;option.dataset.channels=automatic.channels;}
  select.replaceChildren(option);
  for(const d of inventory.devices){const item=new Option(`${d.name} / ${d.backend} / ${d.default_sample_rate} Hz`,String(d.id));item.dataset.rate=d.default_sample_rate;item.dataset.channels=d.channels;select.append(item);}
  select.value=value==null?'':String(value);
  if(select.selectedIndex<0)select.selectedIndex=0;
}
async function refreshRecovery(){
  if(recoveryLoading)return;
  recoveryLoading=true;$('recovery-note').textContent='Enumerating available inputs…';
  try{inputInventory=await api('devices');deviceOptions($('recovery-device'),inputInventory,state.config?.device);$('recovery-note').textContent=inputInventory.error || `${inputInventory.devices.length} inputs available. Switching uses the selected input’s native rate.`;}
  catch(error){$('recovery-note').textContent=error.message;}
  finally{recoveryLoading=false;}
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
  toast('Configuration applied.');
}
function clearReadouts() {
  for (const id of ['rms','dominant','centroid','latency']) $(id).textContent='—';
  $('peak-detail').textContent='NO CURRENT SAMPLES';
  $('noise-detail').textContent='NO CURRENT NOISE ESTIMATE';
  $('spectrogram-detail').textContent=`${state.spectra.length} FRAMES / 180 MAX`;
  $('spectrogram-span').textContent=state.spectraTimes.length?`${number((state.spectraTimes.at(-1)-state.spectraTimes[0])/1000,1)} s HISTORY`:'0.0 s HISTORY';
  $('shift-value').textContent='—';$('shift-value').style.color='#81917d';
  $('shift-status').textContent='NO CURRENT ESTIMATE';$('shift-marker').classList.add('hidden');
  $('observed-detail').textContent='OBSERVED — Hz';
  $('bearing-overlay').classList.remove('hidden');$('bearing-mode').textContent='UNAVAILABLE';
  for (const id of ['bearing-value','bearing-confidence','bearing-uncertainty']) $(id).textContent='—';
  $('bearing-note').textContent='No current acquisition data';
  $('harmonics').textContent='Awaiting current spectral measurements.';
}
function connect() {
  if (state.socket) { state.socket.onclose = null; state.socket.close(); }
  const socket = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/ws`);
  state.socket = socket;
  socket.onopen = () => { state.connected=true;state.linkLost=false; $('connection-light').classList.remove('offline'); $('connection-label').textContent='CONNECTED'; };
  socket.onmessage = event => {
    if(state.socket!==socket)return;
    state.lastReceived=Date.now();state.linkLost=false;
    try { render(JSON.parse(event.data)); } catch (error) { console.error('Measurement render failed',error); }
  };
  socket.onerror = () => { $('connection-label').textContent='RECONNECTING'; };
  socket.onclose = () => {
    state.connected=false;state.linkLost=true; $('connection-light').classList.add('offline'); $('connection-label').textContent='DISCONNECTED';
    if(state.frame)render({...state.frame,measurement_valid:false});
    clearTimeout(state.reconnect); state.reconnect=setTimeout(async () => {
      try { const session=await api('session'); if (session.authenticated) connect(); else if (!$('login-dialog').open) $('login-dialog').showModal(); }
      catch { connect(); }
    },2000);
  };
}
function render(frame) {
  if (frame.config && frame.config_revision!==state.configRevision) {
    applyConfig(frame.config);state.configRevision=frame.config_revision;
  }
  if (frame.stream_id && frame.stream_id!==state.streamId) {
    state.streamId=frame.stream_id;state.sequence=-1;state.spectra.length=0;state.spectraTimes.length=0;
  }
  const status=frame.status || {}, simulation=status.source === 'simulation';
  const paused=!status.running, error=state.linkLost?'Connection lost. Awaiting current station telemetry.':status.error;
  const valid=!state.linkLost && (frame.measurement_valid ?? (!paused && !error && !!frame.spectrum_dbfs));
  frame={...frame,measurement_valid:valid};state.frame=frame;
  const station=state.linkLost?'LINK LOST':error?'INPUT FAULT':paused?'HOLD':valid?'ACQUIRING':'AWAITING INPUT';
  $('station-state').textContent=station;$('station-input').textContent=status.input?.name || (simulation?'SYNTHETIC GENERATOR':'MICROPHONE');
  $('sample-age').textContent=state.linkLost?'UNKNOWN':frame.sample_age_seconds==null?'—':number(frame.sample_age_seconds,2)+' s';
  document.querySelector('.station-strip').classList.toggle('fault',!!error);
  document.querySelector('.metrics').classList.toggle('stale',!valid);
  $('source-badge').classList.toggle('live',!simulation);
  $('source-badge').textContent=simulation?'SIMULATION':'LIVE MICROPHONE';
  $('demo-notice').classList.toggle('hidden',!simulation);
  $('demo-label').textContent=state.linkLost?'Simulation link lost':error?'Simulation unavailable':paused?'Simulation paused':valid?'Synthetic signal active':'Simulation preparing';
  $('capture-button').textContent=paused?'Start acquisition':'Pause acquisition';
  $('capture-button').disabled=state.linkLost;
  $('settings-button').disabled=state.linkLost;
  $('calibrate-button').disabled=paused || !!error || !valid;
  const notice=error || (status.warnings || []).join(' ');
  $('error-banner').classList.toggle('hidden',!notice); $('error-banner').textContent=notice || '';
  const showRecovery=!simulation && !!status.error;
  $('input-recovery').classList.toggle('hidden',!showRecovery);
  if(showRecovery && !recoveryVisible)refreshRecovery();
  recoveryVisible=showRecovery;
  $('system-source').textContent=simulation?'SIMULATION':'MICROPHONE';
  $('sample-rate').textContent=number(status.sample_rate)+' Hz'; $('channels').textContent=status.channels;
  $('mic-state').textContent=state.linkLost?'UNKNOWN':status.microphone_active?'CAPTURING':simulation?'INACTIVE':error?'UNAVAILABLE':paused?'STOPPED':'CONNECTING';
  $('clients').textContent=status.clients; $('buffer-detail').textContent=`${status.overruns || 0} BUFFER OVERRUNS · ${paused?'PAUSED':'BOUNDED QUEUE'}`;
  $('health').textContent=station;
  $('fft-detail').textContent=`HANN WINDOW · ${number(status.fft_size)} SAMPLES · HOP ${number(status.hop_size)}`;
  const baseline=frame.baseline || {};
  $('baseline-status').textContent=baseline.calibrating?'CALIBRATING':baseline.ready?'CALIBRATED':'UNCALIBRATED';
  $('baseline-heading').textContent=baseline.calibrating?'Learning the environment…':baseline.ready?'Your reference is set.':'Learn the room.';
  $('baseline-description').textContent=baseline.calibrating?`${Math.round(baseline.progress*100)}% complete. Keep the environment representative and quiet.`:baseline.ready?'Changes are compared against the calibrated spectral profile. Quiet frames adapt only when enabled.':'Calibrate a quiet interval to detect spectral changes against your environment.';
  $('calibration-progress').style.width=(baseline.progress || 0)*100+'%';
  $('calibrate-button').textContent=baseline.calibrating?'↻ Recalibrate baseline':'↻ Calibrate baseline';
  window.renderResearch?.(frame);
  if (!frame.spectrum_dbfs || !valid) { clearReadouts();drawAll();return; }
  state.frame=frame;
  if (frame.sequence !== state.sequence) {
    state.sequence=frame.sequence;
    state.spectra.push(frame.spectrum_dbfs); if (state.spectra.length>180) state.spectra.shift();
    state.spectraTimes.push(Date.parse(frame.timestamp));if(state.spectraTimes.length>180)state.spectraTimes.shift();
  }
  $('rms').textContent=number(frame.rms_dbfs,1); $('dominant').textContent=number(frame.peaks?.[0]?.hz,1);
  $('peak-detail').textContent=frame.peaks?.length?`${frame.peaks.length} PEAKS · ${number(frame.peaks[0].snr_db,1)} dB ABOVE FLOOR`:'No reliable spectral peaks';
  $('centroid').textContent=number(frame.centroid_hz); $('latency').textContent=number(frame.processing_ms,1);
  $('noise-detail').textContent=`NOISE FLOOR ${number(frame.noise_floor_dbfs,1)} dBFS`;
  $('spectrogram-detail').textContent=`${state.spectra.length} FRAMES / 180 MAX`;
  $('spectrogram-span').textContent=`${number((state.spectraTimes.at(-1)-state.spectraTimes[0])/1000,1)} s HISTORY`;
  $('frame-number').textContent=`FRAME ${String(frame.sequence).padStart(6,'0')}`;
  const shift=frame.shift, shiftValid=shift?.reliable;
  $('shift-value').textContent=shiftValid?(shift.hz>=0?'+':'−')+number(Math.abs(shift.hz),1):'—';
  $('shift-value').style.color=shift.color; $('shift-status').textContent=shiftValid?'VALID ESTIMATE':shift.status.toUpperCase();
  $('shift-description').textContent=simulation?'Controlled synthetic frequency shift':'Spectrum shift · motion unconfirmed';
  $('observed-detail').textContent=`OBSERVED ${number(shift.observed_hz,1)} Hz`;
  $('shift-marker').classList.toggle('hidden',!shiftValid);
  if (shiftValid) $('shift-marker').style.left=(50+Math.max(-1,Math.min(1,shift.hz/(state.config?.shift_range_hz || 200)))*50)+'%';
  const direction=frame.direction || {};
  $('bearing-overlay').classList.toggle('hidden',!!direction.available);
  const paired=direction.mode==='two_microphone', bearings=direction.possible_bearings_deg || [direction.bearing_deg];
  $('bearing-mode').textContent=direction.simulated?(paired?'SIMULATED / TWO MIC':'SIMULATED'):direction.available?(paired?'TWO MIC / AMBIGUOUS':'EXPERIMENTAL'):'UNAVAILABLE';
  $('bearing-value').classList.toggle('paired',paired);
  $('bearing-caption').textContent=paired?'POSSIBLE BEARINGS':'BEARING';
  $('bearing-value').replaceChildren(document.createTextNode(direction.available?bearings.map(v=>number(v,1)).join(' / '):'—'),unit('°'));
  $('bearing-confidence').replaceChildren(document.createTextNode(direction.available?number(direction.confidence*100):'—'),unit('%'));
  $('bearing-uncertainty').replaceChildren(document.createTextNode(direction.available?'±'+number(direction.uncertainty_deg):'—'),unit('°'));
  $('bearing-note').textContent=!direction.available?(direction.reason || 'Synchronized calibrated input required'):paired?`${direction.simulated?'Simulated · ':''}Front/back unresolved${Number.isFinite(direction.delay_seconds)?' · delay '+number(direction.delay_seconds*1e6,1)+' µs':''} · horizontal-plane assumption`:direction.simulated?'Synthetic bearing · demonstration only':'Experimental far-field array estimate';
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
  if (!frame?.spectrum_dbfs || frame.measurement_valid===false) { ctx.textAlign='center';ctx.fillText('NO CURRENT ACQUISITION DATA',w/2,h/2);return; }
  const frequencies=frame.frequencies,values=frame.spectrum_dbfs;
  const yFor=db=>a.y+Math.max(0,Math.min(1,-db/100))*a.h;
  ctx.save();ctx.beginPath();ctx.rect(a.x,a.y,a.w,a.h);ctx.clip();
  if(frame.deviation_db) {
    ctx.fillStyle='#d5b87935';
    frame.deviation_db.forEach((v,i)=>{if(Math.abs(v)>=(state.config?.event_threshold_db || 12))ctx.fillRect(xFor(frequencies[i]),a.y,Math.max(2,a.w/values.length),a.h);});
  }
  if (frame.baseline?.mean_dbfs) {
    ctx.strokeStyle=palette.amber;ctx.lineWidth=1;ctx.setLineDash([3,4]);ctx.beginPath();
    frame.baseline.mean_dbfs.forEach((v,i)=>{const x=xFor(frequencies[i]),y=yFor(v);i?ctx.lineTo(x,y):ctx.moveTo(x,y);});ctx.stroke();ctx.setLineDash([]);
  }
  const gradient=ctx.createLinearGradient(0,a.y,0,a.y+a.h);gradient.addColorStop(0,'#c1d98d38');gradient.addColorStop(1,'#c1d98d00');
  ctx.beginPath();ctx.moveTo(xFor(frequencies[0]),a.y+a.h);values.forEach((v,i)=>ctx.lineTo(xFor(frequencies[i]),yFor(v)));ctx.lineTo(xFor(frequencies.at(-1)),a.y+a.h);ctx.closePath();ctx.fillStyle=gradient;ctx.fill();
  ctx.beginPath();values.forEach((v,i)=>{const x=xFor(frequencies[i]),y=yFor(v);i?ctx.lineTo(x,y):ctx.moveTo(x,y);});ctx.strokeStyle=palette.green;ctx.lineWidth=1.4;ctx.stroke();
  ctx.fillStyle=palette.green;
  for (const peak of frame.peaks.slice(0,4)) { const x=xFor(peak.hz),y=yFor(peak.dbfs);ctx.beginPath();ctx.arc(x,y,2.5,0,Math.PI*2);ctx.fill();ctx.textAlign='center';ctx.fillText(number(peak.hz)+' Hz',x,Math.max(a.y+10,y-10)); }
  ctx.restore();
}
const heatStops=[[9,18,12],[30,54,34],[63,98,60],[142,172,99],[224,204,122],[249,239,202]];
function heat(value) {
  const v=Math.max(0,Math.min(.99999,(value+100)/90))*(heatStops.length-1),i=Math.floor(v),t=v-i;
  return heatStops[i].map((c,j)=>Math.round(c+(heatStops[i+1][j]-c)*t));
}
const heatCanvas=document.createElement('canvas');
const heatLut=new Uint8Array(Array.from({length:256},(_,i)=>heat(-100+i/255*90)).flat());
function spectrogram() {
  const chartData=chart('spectrogram'); if (!chartData) return;
  const {ctx,w,h}=chartData,left=42,bottom=25,rows=180,bins=state.config?.display_bins || 384;
  if(heatCanvas.width!==bins)heatCanvas.width=bins;if(heatCanvas.height!==rows)heatCanvas.height=rows;
  const hc=heatCanvas.getContext('2d'),data=hc.createImageData(bins,rows);
  for(let y=0;y<rows;y++) for(let x=0;x<bins;x++) {
    const sourceRow=state.spectra[y-(rows-state.spectra.length)],value=sourceRow?sourceRow[x]:-140,level=Math.max(0,Math.min(255,Math.round((value+100)/90*255))),offset=(y*bins+x)*4;
    data.data[offset]=heatLut[level*3];data.data[offset+1]=heatLut[level*3+1];data.data[offset+2]=heatLut[level*3+2];data.data[offset+3]=255;
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
  for(const visual of state.frame?.integrations?.visual_observations || []) {
    const center=(visual.fov_center_deg-90)*Math.PI/180, half=visual.fov_width_deg*Math.PI/360;
    ctx.fillStyle='#ad8be327';ctx.strokeStyle='#ad8be3';ctx.setLineDash([3,4]);ctx.beginPath();ctx.moveTo(x,y);ctx.arc(x,y,r,center-half,center+half);ctx.closePath();ctx.fill();ctx.stroke();ctx.setLineDash([]);
  }
  const direction=state.frame?.direction;if(!direction?.available || state.frame.measurement_valid===false)return;
  const bearings=direction.possible_bearings_deg || [direction.bearing_deg];
  const drawBearing=(bearing,uncertainty,color)=>{
    const a=(bearing-90)*Math.PI/180,u=uncertainty*Math.PI/180;
    ctx.beginPath();ctx.moveTo(x,y);ctx.arc(x,y,r,a-u,a+u);ctx.closePath();ctx.fillStyle=color+'22';ctx.fill();
    ctx.strokeStyle=color;ctx.setLineDash(bearings.length>1?[4,4]:[]);ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(x+Math.cos(a)*r,y+Math.sin(a)*r);ctx.stroke();ctx.setLineDash([]);
    ctx.fillStyle=color;ctx.beginPath();ctx.arc(x+Math.cos(a)*r*.85,y+Math.sin(a)*r*.85,4,0,Math.PI*2);ctx.fill();
  };
  const history=state.frame?.bearing_history || [];
  history.slice(-35).forEach((point,i)=>{for(const bearing of point.possible_bearings_deg || [point.bearing_deg]){if(!Number.isFinite(bearing))continue;const a=(bearing-90)*Math.PI/180;ctx.fillStyle=`rgba(94,227,170,${.08+i/50})`;ctx.beginPath();ctx.arc(x+Math.cos(a)*r*.85,y+Math.sin(a)*r*.85,1.8,0,Math.PI*2);ctx.fill();}});
  bearings.forEach((bearing,i)=>drawBearing(bearing,direction.uncertainty_deg ?? 12,i===0?'#5ee3aa':'#d5b879'));

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
    cells.forEach((value,i)=>{const cell=document.createElement('td');cell.textContent=value;if(i===3)cell.className='change';if(i===1){const button=document.createElement('button');button.className='text-button';button.textContent=value;button.onclick=()=>window.reviewEvent?.(event.id);cell.replaceChildren(button);}row.append(cell);});
    node.append(row);
  }
}
async function refreshEvents() {
  if(!state.config)return;
  try{
    const result=await api('events?limit=5');state.events=result.events;$('event-count').textContent=result.total ?? state.events.length;
    eventRows(state.events,$('recent-events'));$('events-empty').classList.toggle('hidden',!!state.events.length);
    if(state.view==='events' && state.archiveNewest!==state.events[0]?.id)await refreshArchive();
  }catch(error){console.warn('Event update',error.message);}
}
async function refreshArchive(){
  const filter=$('event-filter').value;
  const selected=await api(`events?limit=${state.archiveLimit}${filter?'&category='+encodeURIComponent(filter):''}`);
  state.archiveEvents=selected.events;state.archiveNewest=state.events[0]?.id;
  eventRows(state.archiveEvents,$('archive-events'),true);$('archive-empty').classList.toggle('hidden',!!state.archiveEvents.length);
  $('archive-shown').textContent=`${state.archiveEvents.length} OBSERVATIONS SHOWN / ${selected.total ?? '—'} STORED`;
  $('archive-more').classList.toggle('hidden',state.archiveEvents.length<state.archiveLimit || state.archiveLimit>=5000);
}
function view(name){state.view=name;$('monitor-view').classList.toggle('hidden',name!=='monitor');$('archive-view').classList.toggle('hidden',name!=='events');document.querySelectorAll('[data-view]').forEach(button=>button.classList.toggle('active',button.dataset.view===name));if(name==='events')refreshArchive().catch(error=>toast(error.message,true));drawAll();}
async function openSettings(){
  const c=state.config;if(!c)return;
  $('setting-source').value=c.source;$('setting-rate').value=c.sample_rate;$('setting-fft').value=c.fft_size;$('setting-tolerance').value=c.zero_tolerance_hz;$('setting-calibration').value=c.calibration_seconds;$('setting-harmonics').checked=c.harmonics_enabled;
  $('setting-stereo-sync').checked=c.stereo_synchronized;$('setting-stereo-spacing').value=c.stereo_spacing_m;$('setting-stereo-axis').value=c.stereo_axis_deg;$('setting-channels').value=c.channels;$('setting-hop').value=c.hop_size;$('setting-hop').max=c.fft_size;$('setting-geometry').value=JSON.stringify(c.mic_positions || []);
  $('settings-dialog').showModal();$('device-note').textContent='Checking input devices…';
  try{inputInventory=await api('devices');deviceOptions($('setting-device'),inputInventory,c.device);$('device-note').textContent=inputInventory.error || `${inputInventory.devices.length} inputs found. Selecting an input sets its native sample rate. Requested channels: ${c.channels}.`;}
  catch(error){$('device-note').textContent=error.message;}
}
function bind(id,event,fn){$(id).addEventListener(event,async e=>{const button=e.currentTarget.tagName==='BUTTON'?e.currentTarget:e.submitter;if(button)button.disabled=true;try{await fn(e);}catch(error){toast(error.message,true);}finally{if(button)button.disabled=false;}});}
document.querySelectorAll('[data-view]').forEach(button=>button.addEventListener('click',()=>view(button.dataset.view)));
bind('capture-button','click',async()=>{const action=state.frame?.status.running?'stop':'start';await api('capture/'+action,'POST');render(await api('measurements'));toast(action==='stop'?'Acquisition paused. Microphone stream closed.':'Acquisition started.');});
bind('calibrate-button','click',async()=>{await api('baseline/calibrate','POST');toast('Baseline calibration started. Keep the environment quiet.');});
bind('use-microphone','click',()=>openSettings().then(()=>{$('setting-source').value='microphone';}));
bind('apply-reference','click',()=>configure({reference_hz:Number($('reference-hz').value),shift_range_hz:Number($('shift-range').value)}));
$('threshold').addEventListener('input',()=>{$('threshold-label').textContent=$('threshold').value+' dB';});
bind('threshold','change',async()=>{try{await configure({event_threshold_db:Number($('threshold').value)});}catch(error){applyConfig(state.config);throw error;}});
bind('adapt-baseline','change',async()=>{try{await configure({baseline_adaptation:$('adapt-baseline').checked});}catch(error){applyConfig(state.config);throw error;}});
bind('settings-button','click',openSettings);bind('close-settings','click',()=>$('settings-dialog').close());bind('cancel-settings','click',()=>$('settings-dialog').close());
bind('settings-form','submit',async e=>{e.preventDefault();let geometry;try{geometry=JSON.parse($('setting-geometry').value);}catch{throw new Error('Array geometry must be valid JSON, for example [[0,0],[0.04,0],[0,0.04]], or [].');}await configure({source:$('setting-source').value,device:$('setting-device').value===''?null:Number($('setting-device').value),sample_rate:Number($('setting-rate').value),fft_size:Number($('setting-fft').value),channels:Number($('setting-channels').value),hop_size:Number($('setting-hop').value),mic_positions:geometry,stereo_synchronized:$('setting-stereo-sync').checked,stereo_spacing_m:Number($('setting-stereo-spacing').value),stereo_axis_deg:Number($('setting-stereo-axis').value),zero_tolerance_hz:Number($('setting-tolerance').value),calibration_seconds:Number($('setting-calibration').value),harmonics_enabled:$('setting-harmonics').checked});$('settings-dialog').close();});
bind('setting-device','change',()=>{const option=$('setting-device').selectedOptions[0];if(option?.dataset.rate)$('setting-rate').value=option.dataset.rate;if(option?.dataset.channels){$('setting-channels').max=option.dataset.channels;$('setting-channels').value=Math.min(Number($('setting-channels').value),Number(option.dataset.channels));}$('setting-geometry').value='[]';$('setting-stereo-sync').checked=false;});
bind('setting-source','change',()=>{if($('setting-source').value==='microphone'){const option=$('setting-device').selectedOptions[0];if(option?.dataset.rate)$('setting-rate').value=option.dataset.rate;}});
bind('setting-fft','change',()=>{const max=Number($('setting-fft').value);$('setting-hop').max=max;if(Number($('setting-hop').value)>max)$('setting-hop').value=max;});
bind('show-archive','click',()=>view('events'));bind('event-filter','change',async()=>{state.archiveLimit=200;await refreshArchive();});
bind('archive-more','click',async()=>{state.archiveLimit=Math.min(5000,state.archiveLimit+200);await refreshArchive();});
bind('recovery-refresh','click',refreshRecovery);
bind('recovery-retry','click',async()=>{await api('capture/stop','POST');await api('capture/start','POST');toast('Input retry requested. Recovery controls remain available.');});
bind('recovery-apply','click',async()=>{
  const selected=$('recovery-device').selectedOptions[0];
  if(!selected)throw new Error('Refresh inputs and select a microphone.');
  const device=selected.value===''?null:Number(selected.value),channels=Math.min(state.config.channels,Number(selected.dataset.channels) || state.config.channels);
  const changes={source:'microphone',device,sample_rate:Number(selected.dataset.rate) || state.config.sample_rate,channels};
  if(device!==state.config.device || channels!==state.config.channels){changes.mic_positions=[];changes.stereo_synchronized=false;}
  await configure(changes);await api('capture/stop','POST');await api('capture/start','POST');
  toast('Selected input applied. Waiting for live samples.');
});
$('login-dialog').addEventListener('cancel',e=>e.preventDefault());
bind('login-form','submit',async e=>{e.preventDefault();try{await api('login','POST',{token:$('access-token').value});$('access-token').value='';$('login-error').textContent='';$('login-dialog').close();await initialize();}catch(error){$('login-error').textContent=error.message;}});
window.addEventListener('resize',drawAll);
setInterval(()=>{$('clock').textContent=new Date().toLocaleTimeString('en-GB')+' LOCAL';},1000);
setInterval(refreshEvents,2000);
setInterval(()=>{if(state.connected && state.lastReceived && Date.now()-state.lastReceived>5000)state.socket?.close();},1000);
async function initialize(){try{const session=await api('session');if(!session.authenticated){$('login-dialog').showModal();return;}applyConfig(await api('config'));render(await api('measurements'));await refreshEvents();connect();}catch(error){$('error-banner').textContent='Cannot connect to PULSAR: '+error.message;$('error-banner').classList.remove('hidden');}}
initialize();
