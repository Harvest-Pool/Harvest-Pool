(()=>{'use strict';
 const root=document.getElementById('mp-grid');if(!root)return;
 const input=document.getElementById('mp-search'), sort=document.getElementById('mp-sort'), count=document.getElementById('mp-count'), line=document.getElementById('mp-result-text'), empty=document.getElementById('mp-empty'), chips=Array.from(document.querySelectorAll('[data-filter]'));
 const cards=Array.from(root.querySelectorAll('.mp-card'));let filter='all';
 const norm=v=>(v||'').toLocaleLowerCase().trim();
 function update(){const q=norm(input.value);let visible=cards.filter(c=>(filter==='all'||norm(c.dataset.crop).includes(norm(filter)))&&(!q||[c.dataset.crop,c.dataset.place,c.dataset.quality].some(v=>norm(v).includes(q))));
 const mode=sort.value;visible.sort((a,b)=>mode==='price-asc'?Number(a.dataset.price)-Number(b.dataset.price):mode==='price-desc'?Number(b.dataset.price)-Number(a.dataset.price):mode==='quantity-desc'?Number(b.dataset.quantity)-Number(a.dataset.quantity):mode==='crop'?a.dataset.crop.localeCompare(b.dataset.crop):Number(a.dataset.rank)-Number(b.dataset.rank));
 const ids=new Set(visible);cards.forEach(c=>c.hidden=!ids.has(c));visible.forEach(c=>root.appendChild(c));count.textContent=String(visible.length);line.textContent=`Showing ${visible.length} available listing${visible.length===1?'':'s'}`;empty.hidden=visible.length!==0;chips.forEach(c=>{const active=c.dataset.filter===filter;c.classList.toggle('selected',active);c.setAttribute('aria-pressed',active?'true':'false');});}
 function clear(){filter='all';input.value='';sort.value='newest';const u=new URL(window.location.href);u.searchParams.delete('q');history.replaceState({},'',u.pathname+u.search);update();}
 input.addEventListener('input',update);sort.addEventListener('change',update);chips.forEach(c=>c.addEventListener('click',()=>{filter=c.dataset.filter;update();}));document.getElementById('mp-clear').addEventListener('click',clear);document.getElementById('mp-empty-clear').addEventListener('click',clear);update();
})();
