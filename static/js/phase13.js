(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const launch=$('assistant-launch'), panel=$('assistant-panel');
  const input=$('assistant-input'), chat=$('assistant-chat'), lang=$('assistant-lang'), state=$('assistant-state');
  const mic=$('assistant-mic'), send=$('assistant-send');
  let sound = false, recognition = null, lastAnswer = '';
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const soundButton = $('assistant-sound');
  function voiceForLanguage() {
    const wanted = lang.value.toLowerCase();
    const voices = window.speechSynthesis?.getVoices() || [];
    return voices.find(voice => voice.lang.toLowerCase() === wanted) ||
      voices.find(voice => voice.lang.toLowerCase().split('-')[0] === wanted.split('-')[0]);
  }
  function setSound(enabled) {
    sound = enabled;
    soundButton.setAttribute('aria-pressed', String(sound));
    soundButton.textContent = sound ? 'Read answers aloud: On' : 'Read answers aloud: Off';
  }
  try {
    const saved = localStorage.getItem('harvest-guide-language');
    if (Array.from(lang.options).some(option => option.value === saved)) lang.value = saved;
  } catch {}
  lang.addEventListener('change', () => {
    try { localStorage.setItem('harvest-guide-language', lang.value); } catch {}
    recognition?.abort();
    window.speechSynthesis?.cancel();
    chat.replaceChildren();
    state.textContent = '';
    lastAnswer = '';
  });

  function toggle(show) {
    panel.hidden = !show;
    launch.setAttribute('aria-expanded', String(show));
    if (show) {
      input.focus();
    } else {
      recognition?.abort();
      window.speechSynthesis?.cancel();
      launch.focus();
    }
  }
  panel.addEventListener('keydown', event => {
    if (event.key === 'Escape') toggle(false);
  });

  launch?.addEventListener('click',()=>toggle(panel.hidden));
  $('assistant-close')?.addEventListener('click',()=>toggle(false));
  const addMessage=(content,who,url)=>{
    const p=document.createElement('p');p.className='assistant-message '+(who==='user'?'assistant-question':'assistant-answer');p.textContent=content;
    if(url && /^\/(?!\/)/.test(url)){const a=document.createElement('a');a.className='assistant-link';a.href=url;a.textContent='Open suggested page ↗';p.appendChild(document.createElement('br'));p.appendChild(a);}
    chat.appendChild(p);chat.scrollTop=chat.scrollHeight;
  };
  function say(text) {
    if (!sound || panel.hidden) return;
    const voice = voiceForLanguage();
    if (!voice) {
      state.textContent += ' No installed voice matches the selected language.';
      return;
    }
    speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.voice = voice;
    utterance.lang = voice.lang;
    utterance.onerror = event => {
      if (!['canceled', 'interrupted'].includes(event.error)) {
        state.textContent += ' The browser could not play the answer.';
      }
    };
    speechSynthesis.speak(utterance);
  }

  soundButton.addEventListener('click', () => {
    if (!window.speechSynthesis) {
      state.textContent = 'Read-aloud is unavailable in this browser.';
      return;
    }
    setSound(!sound);
    if (!sound) speechSynthesis.cancel();
    else if (lastAnswer) {
      state.textContent = '';
      say(lastAnswer);
    } else if (!voiceForLanguage()) {
      state.textContent = 'No installed voice matches this language yet.';
    }
  });
  $('assistant-form')?.addEventListener('submit',async e=>{
    e.preventDefault();const question=input.value.trim();if(!question || send.disabled)return;
    addMessage(question,'user');input.value='';send.disabled=true;state.textContent='Thinking…';
    try{
      const r=await fetch('/api/assistant/ask',{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':document.querySelector('meta[name="csrf-token"]')?.content || ''},credentials:'same-origin',body:JSON.stringify({message:question,language:lang.value})});
      const data = r.headers.get('content-type')?.includes('application/json') ? await r.json() : {};
      if (!r.ok) throw new Error(data.error || (r.status === 429 ? 'Too many questions. Please wait a minute.' : 'Could not connect. Refresh the page or try again.'));
      if (!data.answer) throw new Error('Harvest Guide returned an empty response.');
      addMessage(data.answer,'bot',data.suggested_url);
      lastAnswer = data.answer;
      state.textContent = data.notice || 'AI assistance';
      say(lastAnswer);
    }catch(err){state.textContent = err.message || 'Connection unavailable.'; input.value = question;}
    finally{send.disabled=false;lang.disabled=false;if(!panel.hidden)input.focus();}
  });
  const speechErrors = {
    'not-allowed': 'Microphone permission was denied. Allow microphone access for Harvest Pool in your browser.',
    'service-not-allowed': 'Your browser has disabled its speech recognition service. Try Chrome or Edge on localhost.',
    'audio-capture': 'No microphone was available. Check your device and browser input settings.',
    'language-not-supported': 'Your browser does not support speech recognition in this language. You can type instead.',
    'network': 'The browser speech service could not connect. Check your connection or type instead.',
    'no-speech': 'I did not hear any speech. Try the microphone again.',
  };
  mic.addEventListener('click', () => {
    if (!window.isSecureContext) {
      state.textContent = 'Microphone access requires HTTPS or http://localhost.';
      return;
    }
    if (!SpeechRecognition) {
      state.textContent = 'Speech recognition is unavailable in this browser. Try Chrome or Edge, or type your question.';
      return;
    }
    if (recognition) {
      recognition.stop();
      return;
    }
    if (send.disabled) return;
    const capture = new SpeechRecognition();
    recognition = capture;
    capture.lang = lang.value;
    capture.interimResults = false;
    capture.onresult = event => {
      if (panel.hidden || capture.lang !== lang.value) return;
      input.value = event.results[0][0].transcript.trim().slice(0, input.maxLength);
      if (window.speechSynthesis) setSound(true);
      $('assistant-form').requestSubmit();
    };
    capture.onerror = event => {
      if (event.error !== 'aborted') {
        state.textContent = speechErrors[event.error] || 'Speech recognition stopped. Try again or type your question.';
      }
    };
    capture.onend = () => {
      recognition = null;
      mic.textContent = '??';
      mic.setAttribute('aria-pressed', 'false');
      if (state.textContent === 'Listening?') state.textContent = '';
    };
    try {
      window.speechSynthesis?.cancel();
      capture.start();
      mic.textContent = '?';
      mic.setAttribute('aria-pressed', 'true');
      state.textContent = 'Listening?';
    } catch {
      recognition = null;
      state.textContent = 'Could not start the microphone. Check browser permissions and try again.';
    }
  });
  const output=$('live-discovery');
  document.querySelectorAll('.crop-chip[data-crop]').forEach(button=>button.addEventListener('click',async()=>{
    document.querySelectorAll('.crop-chip[data-crop]').forEach(x=>x.classList.toggle('active',x===button));
    output.textContent='Searching available produce…';
    try{
      const res=await fetch('/api/discover?q='+encodeURIComponent(button.dataset.crop));if(!res.ok)throw new Error();
      const data=await res.json();output.replaceChildren();
      if(!data.items.length){output.textContent='No matching produce published right now.';return;}
      data.items.forEach(item=>{
        const a=document.createElement('a');a.href=item.detail_url;
        if(item.photo_url){const img=document.createElement('img');img.src=item.photo_url;img.alt='Photo of '+item.crop;a.appendChild(img);}
        const name=document.createElement('strong');name.textContent=item.crop;
        const desc=document.createElement('small');desc.textContent=item.village+' · R'+item.price.toFixed(2)+'/kg · '+item.available_kg+' kg';
        a.append(name,desc);output.appendChild(a);
      });
    }catch(e){output.textContent='Could not load listings. Try the marketplace search.';}
  }));
})();
