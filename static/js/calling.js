(() => {
  'use strict';
  const dialog = document.getElementById('hp-calls');
  if (!dialog) return;
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content;
  const status = document.getElementById('hp-call-status');
  const peer = document.getElementById('hp-call-peer');
  const acceptBtn = document.getElementById('hp-accept-call');
  const declineBtn = document.getElementById('hp-decline-call');
  const muteBtn = document.getElementById('hp-mute-call');
  const endBtn = document.getElementById('hp-end-call');
  const remoteAudio = document.getElementById('hp-remote-audio');
  let call = null, pc = null, stream = null, lastSignal = 0, offerStarted = false;
  let closed = false, busy = false, muted = false, queuedIce = [];

  async function api(path, opts = {}) {
    const res = await fetch('/calls' + path, {
      credentials: 'same-origin', cache: 'no-store',
      ...opts,
      headers: { ...(opts.body ? {'Content-Type': 'application/json', 'X-CSRFToken': csrf} : {}), ...(opts.headers || {}) }
    });
    if (!res.ok) {
      let reason = `Request failed (${res.status})`;
      try { const err = await res.json(); reason = err.error || reason; } catch (_) {}
      throw new Error(reason);
    }
    return res.json();
  }
  const post = (path, payload = {}) => api(path, {method:'POST', body:JSON.stringify(payload)});
  function message(text) { status.textContent = text; }
  function visible(v) {dialog.hidden = !v;}
  function buttons() {
    acceptBtn.hidden = !call || call.direction !== 'incoming' || call.status !== 'ringing';
    declineBtn.hidden = acceptBtn.hidden;
    muteBtn.hidden = !call || call.status !== 'active';
    endBtn.hidden = !call || call.status !== 'ringing' && call.status !== 'active';
    muteBtn.textContent = muted ? 'Unmute' : 'Mute';
  }
  function cleanMedia() {
    if (stream) {stream.getTracks().forEach(t => t.stop()); stream = null;}
    if (pc) {pc.onicecandidate = null; pc.close(); pc = null;}
    remoteAudio.srcObject = null; offerStarted = false; queuedIce = []; muted = false;
  }
  function done(text) {
    cleanMedia(); call = null; lastSignal = 0;
    message(text); buttons();
    window.setTimeout(() => { if (!call) visible(false); }, 1800);
  }
  async function startMedia() {
    if (!navigator.mediaDevices?.getUserMedia) throw new Error('Microphone access requires localhost or an HTTPS website.');
    if (!stream) stream = await navigator.mediaDevices.getUserMedia({audio: {echoCancellation:true,noiseSuppression:true},video:false});
    if (!pc) {
      const ice = await api('/options');
      pc = new RTCPeerConnection({iceServers:ice.iceServers});
      stream.getTracks().forEach(track => pc.addTrack(track,stream));
      pc.onicecandidate = e => {
        if (e.candidate && call) post(`/${call.id}/signal`,{type:'candidate', payload:e.candidate.toJSON()}).catch(console.warn);
      };
      pc.ontrack = e => { remoteAudio.srcObject = e.streams[0]; remoteAudio.play().catch(() => message('Tap the page to enable sound.')); };
      pc.onconnectionstatechange = () => {
        if (pc?.connectionState === 'connected') message('Connected • Voice call');
        if (pc?.connectionState === 'failed') message('Connection failed. A TURN relay may be required.');
      };
    }
  }
  async function offer() {
    if (!call || call.direction !== 'outgoing' || offerStarted) return;
    offerStarted = true;
    try {
      await startMedia();
      const o = await pc.createOffer(); await pc.setLocalDescription(o);
      await post(`/${call.id}/signal`,{type:'offer',payload:{type:o.type,sdp:o.sdp}});
      message('Connecting audio…');
    } catch (err) {message(err.message); await hangup();}
  }
  async function incomingSignal(signal) {
    if (!call) return;
    if (signal.type === 'offer') {
      await startMedia();
      await pc.setRemoteDescription(new RTCSessionDescription(signal.payload));
      await flushIce();
      const answer = await pc.createAnswer(); await pc.setLocalDescription(answer);
      await post(`/${call.id}/signal`,{type:'answer',payload:{type:answer.type,sdp:answer.sdp}});
    } else if (signal.type === 'answer') {
      if (!pc) return;
      await pc.setRemoteDescription(new RTCSessionDescription(signal.payload));
      await flushIce();
    } else if (signal.type === 'candidate') {
      if (!pc?.remoteDescription) queuedIce.push(signal.payload);
      else await pc.addIceCandidate(new RTCIceCandidate(signal.payload));
    }
  }
  async function flushIce() {
    for (const ice of queuedIce) await pc.addIceCandidate(new RTCIceCandidate(ice));
    queuedIce=[];
  }
  async function hangup() {
    if (!call) { done('Call ended'); return; }
    const id=call.id;
    done('Call ended');
    try {await post(`/${id}/end`);} catch (e) {console.warn(e);}
  }
  async function callTarget(orderId,userId,label) {
    if (call) return;
    try {
      const data = await post('/start',{order_id:Number(orderId),target_user_id:Number(userId)});
      call=data.call;lastSignal=0;peer.textContent=label;message('Ringing…');visible(true);buttons();
    } catch(err) {window.alert(err.message);}
  }
  async function checkCall() {
    if (busy || closed || document.hidden) return;
    busy=true;
    try {
      if (!call) {
        const data=await api('/inbox');
        if (data.call) {call=data.call;lastSignal=0;peer.textContent=`Order #${call.order_id} participant`;message('Incoming voice call');visible(true);buttons();}
      } else {
        const data=await api(`/${call.id}?after=${lastSignal}`);
        if (!call || data.call.id !== call.id) return;
        call.status=data.call.status;
        buttons();
        if (['ended','missed','declined'].includes(call.status)) {
          done(call.status==='missed'?'No answer':call.status==='declined'?'Call declined':'Call ended');return;
        }
        if (call.status==='active' && call.direction==='outgoing') await offer();
        for (const signal of data.signals) {
          lastSignal=Math.max(lastSignal,signal.id);
          try {await incomingSignal(signal);} catch(e) {message('Audio connection error: '+e.message);}
        }
      }
    } catch(e) {if (call) message('Connection issue: '+e.message);}
    finally {busy=false;}
  }
  async function renderTargets() {
    for(const section of document.querySelectorAll('[data-call-order-id]')) {
      const orderId=section.dataset.callOrderId;
      try {
        const data=await api(`/targets/${orderId}`);
        const list=section.querySelector('.hp-target-list');
        if (!list) continue;
        list.replaceChildren();
        for(const t of data.targets) {
          const b=document.createElement('button'); b.type='button';b.className='hp-target-button';
          b.textContent=`☎ Call ${t.display_name}`;
          b.addEventListener('click',()=>callTarget(orderId,t.user_id,t.display_name));
          list.append(b);
        }
        if (!data.targets.length) list.textContent='No eligible participants have linked accounts yet.';
      } catch(_) {section.hidden=true;}
    }
  }
  acceptBtn.addEventListener('click', async () => {
    if (!call) return;
    try { await startMedia(); await post(`/${call.id}/accept`);call.status='active';message('Connecting audio…');buttons(); }
    catch(e) {message(e.message);await hangup();}
  });
  declineBtn.addEventListener('click',async()=>{
    if (!call) return; const id=call.id;done('Call declined');
    try {await post(`/${id}/decline`);}catch(e){console.warn(e);}
  });
  endBtn.addEventListener('click', hangup);
  document.getElementById('hp-call-close').addEventListener('click',hangup);
  muteBtn.addEventListener('click',()=>{
    if (!stream) return;muted=!muted;
    stream.getAudioTracks().forEach(t=>{t.enabled=!muted;});buttons();
  });
  window.addEventListener('beforeunload',()=>{closed=true;cleanMedia();});
  renderTargets();
  window.setInterval(checkCall, 1300);
  checkCall();
})();
