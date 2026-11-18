'use strict';
const visionPanel=document.createElement('section');visionPanel.className='panel';
visionPanel.innerHTML=`<div class="panel-header"><h2>ARGOS / live camera</h2><span class="tag">78° FOV / VISUAL</span></div><div class="research-body"><div class="research-controls"><label>Camera index<input id="vision-camera" type="number" min="0" max="32" value="0"></label><label>Camera heading (°)<input id="vision-heading" type="number" min="0" max="359.9" step="0.1" value="0"></label></div><label><input id="vision-identity" type="checkbox" checked> Enable face IDs and enrollment (consenting participants)</label><div class="research-controls"><button id="vision-start" class="button">Start ARGOS camera</button><button id="vision-stop" class="button">Stop camera</button></div><p id="vision-status">Camera stopped. ARGOS catalogue stays local. No automatic enrollment.</p><div class="vision-view"><canvas id="vision-view" aria-label="ARGOS camera viewing window"></canvas><span id="vision-stale">NO LIVE VIDEO</span></div><p id="vision-identity-status"></p><p>Visual vectors and acoustic bearings are separate observations. Fixed-radius markers show direction only; no distance or sound-source identity is inferred.</p><label>Playback buffer (ms)<input id="vision-buffer" type="range" min="0" max="300" step="20" value="160"><output id="vision-buffer-label">160 ms</output></label></div>`;
$('argos-grid').append(visionPanel);
let visionActive=false,visionLastPaint=0;
let visionRoot='',visionSequence=-1,visionBusy=false,visionFrames=[],visionFrame=null,visionReceived=0,visionEpoch=0;
window.currentVision=()=>visionFrame && Date.now()-visionFrame.received+visionFrame.age_seconds*1000<1000?visionFrame:null;
window.currentVisualFaces=()=>{const frame=window.currentVision();return (frame?.faces || []).filter(face=>(Date.now()-frame.received)/1000+frame.age_seconds+Math.max(0,frame.captured_at-face.observed_at)<1);};
const video=$('vision-view');
function clearVision(){visionEpoch++;visionSequence=-1;visionFrames.forEach(frame=>frame.bitmap.close());visionFrames=[];if(visionFrame)visionFrame.bitmap.close();visionFrame=null;video.getContext('2d').clearRect(0,0,video.width,video.height);}
$('vision-buffer').oninput=()=>$('vision-buffer-label').textContent=$('vision-buffer').value+' ms';
async function visionControl(start){
 try{
  clearVision();
  const settings={camera:Number($('vision-camera').value),heading:Number($('vision-heading').value),identity:$('vision-identity').checked};
  if(visionRoot)settings.root=visionRoot;
  const status=await api(start?'v1/vision/start':'v1/vision/stop','POST',start?settings:undefined);
  visionActive=start&&!status.error;
  $('vision-status').textContent=status.error || (start?'Starting ARGOS…':'Camera stopped');
 }catch(error){toast(error.message,true);}
}
$('vision-start').onclick=()=>visionControl(true);$('vision-stop').onclick=()=>visionControl(false);
async function pollVision(){
 if(visionBusy || !state.config || !visionActive)return;visionBusy=true;const epoch=visionEpoch;
 const abort=new AbortController(),timeout=setTimeout(()=>abort.abort(),2500);
 try{
  const response=await fetch('/api/v1/vision/frame?after='+visionSequence,{signal:abort.signal});
  if(response.status!==200)return;
  const frame=await response.json();if(epoch!==visionEpoch)return;
  const bytes=Uint8Array.from(atob(frame.jpeg_base64),c=>c.charCodeAt(0));const bitmap=await createImageBitmap(new Blob([bytes],{type:'image/jpeg'}));
  if(epoch!==visionEpoch){bitmap.close();return;}delete frame.jpeg_base64;
  visionSequence=frame.sequence;visionReceived=Date.now();visionFrames.push({...frame,bitmap,received:visionReceived});
  while(visionFrames.length>6)visionFrames.shift().bitmap.close();
 }catch(error){if(error.name!=='AbortError')console.debug('Vision waiting',error.message);}finally{clearTimeout(timeout);visionBusy=false;}
}
function playback(){
 const now=Date.now(),delay=Number($('vision-buffer').value);if(now-visionLastPaint<33){requestAnimationFrame(playback);return;}visionLastPaint=now;
 while(visionFrames.length && now-visionFrames[0].received>=delay){if(visionFrame)visionFrame.bitmap.close();visionFrame=visionFrames.shift();}
 if(visionFrame && state.view==='argos'){if(video.width!==visionFrame.width || video.height!==visionFrame.height){video.width=visionFrame.width;video.height=visionFrame.height;}
  const ctx=video.getContext('2d');ctx.drawImage(visionFrame.bitmap,0,0);
  for(const face of window.currentVisualFaces()){const [x,y,w,h]=face.box;ctx.strokeStyle=palette.white;ctx.lineWidth=2;ctx.strokeRect(x*video.width,y*video.height,w*video.width,h*video.height);ctx.fillStyle=palette.white;ctx.font='13px "IBM Plex Mono",monospace';ctx.fillText((face.identity_id || 'Unknown')+' / TRK-'+face.track_id,x*video.width,Math.max(15,y*video.height-5));}
 }
 $('vision-stale').classList.toggle('hidden',!!window.currentVision());if(window.currentVision())$('bearing-overlay').classList.add('hidden');
 $('vision-stale').textContent=visionFrame?'STALE / HOLDING LAST FRAME':'NO LIVE VIDEO';
 const visual=window.currentVision(),faces=window.currentVisualFaces();$('ppi-visual-status').textContent=visual?'VISUAL · '+faces.length+' face vector'+(faces.length===1?'':'s')+' · 78° FOV · controls in ARGOS':visionActive?'ARGOS waiting / stale · no current face vectors':'Visual vectors off · camera controls in ARGOS';
 // Repaint visual vectors even when the microphone is stopped.
 if(state.view==='monitor')polar();requestAnimationFrame(playback);
}
async function visionStatus(){if(!state.config)return;try{const s=await api('v1/vision');visionRoot=s.default_root;visionActive=s.running;
 $('vision-status').textContent=s.error || (s.running?(s.stale?'Camera starting / waiting for frames':'ARGOS active · bounded '+$('vision-buffer').value+' ms playback cache'):'Camera stopped');
 $('vision-identity-status').textContent=s.identity_status;
 $('vision-start').disabled=s.running;$('vision-stop').disabled=!s.running&&!s.error;
 if(!s.running && (s.error || s.frame_age_seconds===null))clearVision();
 }catch{}}
const ppiVisualStatus=document.createElement('div');ppiVisualStatus.id='ppi-visual-status';ppiVisualStatus.className='panel-footer';ppiVisualStatus.textContent='Visual vectors off · camera controls in ARGOS';document.querySelector('.polar-panel').append(ppiVisualStatus);
document.querySelector('.polar-panel h2').textContent='Acoustic bearing / PPI';setInterval(pollVision,50);setInterval(visionStatus,1500);requestAnimationFrame(playback);visionStatus();

const cataloguePanel=document.createElement('section');cataloguePanel.className='panel argos-catalogue';cataloguePanel.innerHTML=`<div class="panel-header"><h2>Face enrollment &amp; catalogue</h2><span class="tag" id="catalogue-count">LOCAL</span></div><div class="research-body"><p>Select the visible track before enrolling or associating. Nothing is enrolled automatically.</p><label>Visible track<select id="catalogue-track"></select></label><label>Name<input id="catalogue-name" maxlength="120" placeholder="Participant name"></label><button class="button primary" id="catalogue-enroll">Enroll track</button><label>Saved identity<select id="catalogue-id"></select></label><div class="research-controls"><button class="button" id="catalogue-associate">Associate track</button><button class="button" id="catalogue-rename">Rename</button></div><label>Category<select id="catalogue-category-value"><option>Unknown</option><option>Friendly</option></select></label><div class="research-controls"><button class="button" id="catalogue-category">Set category</button><button class="button" id="catalogue-delete">Delete identity</button></div><p id="catalogue-status" role="status"></p><p>Enroll only consenting participants. Templates stay in ARGOS's local catalogue. InsightFace pretrained weights are for non-commercial research.</p></div>`;$('argos-grid').append(cataloguePanel);
async function loadCatalogue(){
 const result=await api('v1/vision/catalogue'),old=$('catalogue-id').value;
 $('catalogue-id').replaceChildren();
 for(const row of result.identities)$('catalogue-id').append(new Option(row.identity_id+' / '+row.display_name+' / '+row.template_count+' templates',row.identity_id));
 if([...$('catalogue-id').options].some(o=>o.value===old))$('catalogue-id').value=old;
 $('catalogue-count').textContent=result.identities.length+' SAVED';
 const track=$('catalogue-track').value;$('catalogue-track').replaceChildren();
 for(const face of window.currentVisualFaces())$('catalogue-track').append(new Option('TRK-'+face.track_id+' / '+(face.identity_id || 'Unknown'),String(face.track_id)));
 if([...$('catalogue-track').options].some(o=>o.value===track))$('catalogue-track').value=track;
 $('catalogue-status').textContent=result.command_status || 'Start the camera with face IDs enabled, then select a visible track to enroll.';
}
document.addEventListener('pulsar:viewchange',event=>{if(event.detail==='argos')loadCatalogue().catch(e=>toast(e.message,true));});
for(const action of ['enroll','associate','rename','delete','category'])$('catalogue-'+action).onclick=async()=>{try{if(action==='delete'&&!confirm('Permanently delete the selected saved identity and its local templates?'))return;if(action==='enroll'&&!confirm('Enroll the selected visible track with participant consent?'))return;const body={action,identity_id:$('catalogue-id').value || null,track_id:Number($('catalogue-track').value) || null,name:$('catalogue-name').value,category:$('catalogue-category-value').value};await api('v1/vision/catalogue','POST',body);$('catalogue-status').textContent='Command queued; awaiting ARGOS processing.';}catch(e){$('catalogue-status').textContent=e.message;}};
setInterval(()=>{if(state.view==='argos')loadCatalogue().catch(()=>{});},2000);
