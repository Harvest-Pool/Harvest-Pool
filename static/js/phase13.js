(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const launch=$('assistant-launch'), panel=$('assistant-panel');
  const input=$('assistant-input'), chat=$('assistant-chat'), lang=$('assistant-lang'), state=$('assistant-state');
  const mic=$('assistant-mic'), send=$('assistant-send');
  let sound=true, recognition=null;
  const toggle = show => { panel.hidden=!show; launch.setAttribute('aria-expanded',String(show)); if(show) input.focus(); else if(window.speechSynthesis) speechSynthesis.cancel(); };
  launch?.addEventListener('click',()=>toggle(panel.hidden));
  $('assistant-close')?.addEventListener('click',()=>toggle(false));
  const addMessage=(content,who,url)=>{
    const p=document.createElement('p');p.className='assistant-message '+(who==='user'?'assistant-question':'assistant-answer');p.textContent=content;
    if(url && /^\/(?!\/)/.test(url)){const a=document.createElement('a');a.className='assistant-link';a.href=url;a.textContent='Open suggested page ↗';p.appendChild(document.createElement('br'));p.appendChild(a);}
    chat.appendChild(p);chat.scrollTop=chat.scrollHeight;
  };
  const say=text=>{
    if(!sound || !('speechSynthesis' in window))return;
    speechSynthesis.cancel();const u=new SpeechSynthesisUtterance(text);u.lang=lang.value;u.rate=.94;
    const voices=speechSynthesis.getVoices();const v=voices.find(x=>x.lang.toLowerCase()===lang.value.toLowerCase());
    if(v)u.voice=v;else if(lang.value!=='en-ZA'){state.textContent='No matching voice installed; answer shown as text.';return;}
    speechSynthesis.speak(u);
  };
  $('assistant-sound')?.addEventListener('click',e=>{sound=!sound;e.currentTarget.textContent='🔊 Read answers aloud: '+(sound?'On':'Off');if(!sound && window.speechSynthesis)speechSynthesis.cancel();});
  $('assistant-form')?.addEventListener('submit',async e=>{
    e.preventDefault();const question=input.value.trim();if(!question)return;
    addMessage(question,'user');input.value='';send.disabled=true;state.textContent='Thinking…';
    try{
      const r=await fetch('/api/assistant/ask',{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':document.querySelector('meta[name="csrf-token"]')?.content || ''},credentials:'same-origin',body:JSON.stringify({message:question,language:lang.value})});
      const data=await r.json();if(!r.ok)throw new Error(data.error||'Service unavailable');
      addMessage(data.answer,'bot',data.suggested_url);say(data.answer);state.textContent=data.ai_active?'AI assistance':'Guided assistance';
    }catch(err){addMessage('Could not connect. Please try again or use the marketplace search.','bot');state.textContent='Connection issue';}
    finally{send.disabled=false;input.focus();}
  });
  // Speech recognition is browser/device/language-dependent. Text entry always works.
  const SpeechRecognition=window.SpeechRecognition||window.webkitSpeechRecognition;
  if(!SpeechRecognition){mic.title='Voice recognition unavailable in this browser; type instead.';}
  mic?.addEventListener('click',()=>{
    if(!SpeechRecognition){state.textContent='Voice recognition unavailable on this browser.';input.focus();return;}
    if(recognition){recognition.stop();return;}
    const r=new SpeechRecognition();recognition=r;r.lang=lang.value;r.interimResults=false;r.maxAlternatives=1;
    r.onresult=event=>{input.value=event.results[0][0].transcript;state.textContent='Heard your question';$('assistant-form').requestSubmit();};
    r.onerror=event=>{state.textContent='Microphone: '+event.error+'. Try typing.';};
    r.onend=()=>{recognition=null;mic.textContent='🎤';};
    try{r.start();mic.textContent='■';state.textContent='Listening… speak now';}catch(e){state.textContent='Microphone unavailable';recognition=null;}
  });
  const output=$('live-discovery');
  document.querySelectorAll('[data-crop]').forEach(button=>button.addEventListener('click',async()=>{
    document.querySelectorAll('[data-crop]').forEach(x=>x.classList.toggle('active',x===button));
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
