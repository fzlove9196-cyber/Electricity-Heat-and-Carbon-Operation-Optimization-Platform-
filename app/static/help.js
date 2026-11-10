/* 在线帮助（/help）：目录、全文搜索、文章渲染、面包屑、上一篇/下一篇、返回产品。
   ?embed=1 时运行在产品抽屉 iframe 中：「打开此功能」与关闭通过 postMessage 交给产品页处理，不刷新产品、不丢会话。 */
(function(){
  const $=s=>document.querySelector(s);
  const QP=new URLSearchParams(location.search);
  const EMBED=QP.get('embed')==='1';
  if(EMBED)document.body.classList.add('embed');
  let M=null, ORDER=[], IDX=null, cur=null;
  const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const post=msg=>{try{parent.postMessage(Object.assign({source:'sdco-help'},msg),location.origin)}catch(e){}};
  const helpUrl=(slug,hash)=>'/help/'+slug+(EMBED?'?embed=1':'')+(hash?'#'+hash:'');
  const viewUrl=p=>'/?view='+encodeURIComponent(p.view||'chat')+(p.step?'&step='+encodeURIComponent(p.step):'');

  async function j(u){const r=await fetch(u);if(!r.ok)throw Error(r.status+' '+u);return r.json()}

  function slugFromPath(){const m=location.pathname.match(/^\/help\/([a-z0-9][a-z0-9-]{0,63})\/?$/);return m?m[1]:(M&&M.home)||'welcome'}

  function buildToc(){
    const t=$('#hToc');t.innerHTML='';
    M.sections.forEach(s=>{
      const h=document.createElement('div');h.className='sec';h.textContent=s.title;h.onclick=()=>h.classList.toggle('fold');
      const ul=document.createElement('ul');
      s.pages.forEach(slug=>{const p=M.pages[slug];if(!p)return;
        const li=document.createElement('li'),a=document.createElement('a');a.href=helpUrl(slug);a.textContent=p.title;a.dataset.slug=slug;li.appendChild(a);ul.appendChild(li)});
      t.appendChild(h);t.appendChild(ul);
    });
  }

  function decorate(art,page){
    let n=0;const on=[];
    art.querySelectorAll('h2,h3').forEach(h=>{const id='h-'+(++n);h.id=id;
      const a=document.createElement('a');a.href='#'+id;a.className='h-anchor';a.textContent='#';h.appendChild(a);
      on.push(`<a class="l${h.tagName[1]}" href="#${id}">${esc(h.firstChild.textContent)}</a>`)});
    $('#hOnPage').innerHTML=on.length?'<b>本页目录</b>'+on.join(''):'';
    art.querySelectorAll('a[href]').forEach(a=>{
      const href=a.getAttribute('href');
      if(href.startsWith('/?view=')){a.classList.add('open-feature');a.title='在产品中打开此功能（会话保留）';
        if(EMBED)a.addEventListener('click',e=>{e.preventDefault();post({type:'open-view',href})});
      }else if(href.startsWith('/help/')&&!href.startsWith('/help/img/')){
        a.addEventListener('click',e=>{e.preventDefault();const [p,h]=href.slice(6).split('#');go(p,h,true)});
      }else if(/^https?:/.test(href)){a.target='_blank';a.rel='noopener'}
    });
    art.querySelectorAll('img').forEach(img=>{img.loading='lazy';img.addEventListener('click',()=>{
      const z=document.createElement('div');z.className='h-zoom';z.innerHTML='<img alt="">';z.firstChild.src=img.src;z.onclick=()=>z.remove();document.body.appendChild(z)})});
  }

  async function go(slug,hash,push){
    if(!M.pages[slug])slug=M.home||'welcome';
    cur=slug;const meta=M.pages[slug];
    document.body.classList.remove('toc-open');$('#hResults').hidden=true;
    if(push)history.pushState({slug},'',helpUrl(slug,hash));
    document.querySelectorAll('#hToc a').forEach(a=>a.classList.toggle('active',a.dataset.slug===slug));
    const act=document.querySelector('#hToc a.active');
    if(act){act.closest('ul').previousElementSibling.classList.remove('fold');act.scrollIntoView({block:'nearest'})}
    $('#hCrumb').innerHTML=`<a href="${helpUrl(M.home||'welcome')}" data-slug="${M.home||'welcome'}">使用帮助</a> › ${esc(meta.section||'')} › <span>${esc(meta.title)}</span>`;
    $('#hCrumb a').onclick=e=>{e.preventDefault();go(M.home||'welcome',null,true)};
    $('#hBack').href=viewUrl(meta);
    document.title=meta.title+' · 使用帮助';
    const art=$('#hArticle');
    try{const p=await j('/api/help/pages/'+slug);
      art.innerHTML=marked.parse(p.markdown);decorate(art,p);
    }catch(e){art.innerHTML='<p>页面加载失败：'+esc(e.message)+'</p>'}
    const i=ORDER.indexOf(slug),prev=ORDER[i-1],next=ORDER[i+1];
    $('#hPager').innerHTML=(prev?`<a class="prev" href="${helpUrl(prev)}" data-slug="${prev}"><small>← 上一篇</small>${esc(M.pages[prev].title)}</a>`:'<span></span>')+
      (next?`<a class="next" href="${helpUrl(next)}" data-slug="${next}"><small>下一篇 →</small>${esc(M.pages[next].title)}</a>`:'<span></span>');
    $('#hPager').querySelectorAll('a').forEach(a=>a.onclick=e=>{e.preventDefault();go(a.dataset.slug,null,true)});
    if(hash){const el=document.getElementById(hash);if(el){el.scrollIntoView();return}}
    $('#hMain').scrollTop=0;
    if(EMBED)post({type:'page',slug});
  }

  /* ---- 搜索：标题 > 关键词 > 参数名 > 章节标题 > 正文；多词按“与” ---- */
  function score(it,terms){
    let total=0;const hits=[];
    for(const t of terms){let s=0;
      if(it.title.toLowerCase().includes(t))s+=30;
      if(it.keywords.some(k=>k.toLowerCase().includes(t)))s+=15;
      const ps=it.params.filter(p=>p.toLowerCase().includes(t));if(ps.length){s+=12;hits.push(...ps.slice(0,3).map(p=>'`'+p+'`'))}
      const hs=it.headings.filter(h=>h.text.toLowerCase().includes(t));if(hs.length){s+=8;hits.push(...hs.slice(0,2).map(h=>h.text))}
      const c=it._lc.split(t).length-1;if(c)s+=Math.min(c,10);
      if(!s)return null;total+=s}
    return {total,hits:[...new Set(hits)].slice(0,4)};
  }
  function snippet(it,t){const i=it._lc.indexOf(t);if(i<0)return '';return it.text.slice(Math.max(0,i-30),i+70).replace(/\s+/g,' ').trim()}
  let sel=-1;
  async function doSearch(q){
    const box=$('#hResults');q=q.trim().toLowerCase();
    if(!q){box.hidden=true;return}
    if(!IDX){IDX=await j('/api/help/index');IDX.forEach(i=>i._lc=i.text.toLowerCase())}
    const terms=q.split(/\s+/).filter(Boolean);
    const rs=IDX.map(it=>({it,r:score(it,terms)})).filter(x=>x.r).sort((a,b)=>b.r.total-a.r.total).slice(0,15);
    sel=-1;box.hidden=false;
    box.innerHTML=rs.length?rs.map(({it,r})=>`<a href="${helpUrl(it.slug)}" data-slug="${it.slug}"><b>${esc(it.title)}</b>${r.hits.map(h=>`<span class="hit">${esc(h)}</span>`).join('')}<small>${esc(it.section||'')} · ${esc(snippet(it,terms[0]))}</small></a>`).join('')
      :'<a><b>没有找到匹配内容</b><small>试试更短的词，例如「PUE」「绑定」「15分钟」「time_limit_s」</small></a>';
    box.querySelectorAll('a[data-slug]').forEach(a=>a.onclick=e=>{e.preventDefault();openResult(a.dataset.slug,terms[0])});
  }
  function openResult(slug,term){
    $('#hSearch').blur();$('#hResults').hidden=true;
    go(slug,null,true).then(()=>{ // 定位到第一个包含关键词的标题
      const h=[...document.querySelectorAll('#hArticle h2,#hArticle h3')].find(h=>h.textContent.toLowerCase().includes(term));
      if(h)h.scrollIntoView();});
  }

  function bind(){
    let tm;$('#hSearch').addEventListener('input',e=>{clearTimeout(tm);tm=setTimeout(()=>doSearch(e.target.value),120)});
    $('#hSearch').addEventListener('keydown',e=>{const as=[...$('#hResults').querySelectorAll('a[data-slug]')];
      if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault();if(!as.length)return;sel=(sel+(e.key==='ArrowDown'?1:-1)+as.length)%as.length;as.forEach((a,i)=>a.classList.toggle('sel',i===sel))}
      else if(e.key==='Enter'){const a=as[sel<0?0:sel];if(a)openResult(a.dataset.slug,e.target.value.trim().toLowerCase().split(/\s+/)[0])}
      else if(e.key==='Escape'){if(e.target.value){e.target.value='';$('#hResults').hidden=true;e.stopPropagation()}else e.target.blur()}});
    document.addEventListener('click',e=>{if(!e.target.closest('#hSearchBox'))$('#hResults').hidden=true});
    document.addEventListener('keydown',e=>{
      const typing=/INPUT|TEXTAREA/.test(document.activeElement.tagName);
      if(e.key==='/'&&!typing){e.preventDefault();$('#hSearch').focus()}
      if(e.key==='Escape'&&!typing){if(document.querySelector('.h-zoom'))document.querySelector('.h-zoom').remove();else if(EMBED)post({type:'close'})}
    });
    $('#hMenu').onclick=()=>document.body.classList.toggle('toc-open');
    $('#hClose').onclick=()=>post({type:'close'});
    $('#hToc').addEventListener('click',e=>{const a=e.target.closest('a[data-slug]');if(a){e.preventDefault();go(a.dataset.slug,null,true)}});
    window.addEventListener('popstate',()=>go(slugFromPath(),location.hash.slice(1),false));
    window.addEventListener('message',e=>{if(e.origin===location.origin&&e.data&&e.data.source==='sdco-app'&&e.data.type==='goto')go(e.data.slug,null,true)});
  }

  (async function init(){
    try{M=await j('/api/help/manifest')}catch(e){$('#hArticle').innerHTML='<p>帮助目录加载失败：'+esc(e.message)+'</p>';return}
    ORDER=M.sections.flatMap(s=>s.pages).filter(s=>M.pages[s]);
    buildToc();bind();
    const q=QP.get('q');
    await go(slugFromPath(),location.hash.slice(1),false);
    if(q){$('#hSearch').value=q;doSearch(q)}
  })();
})();
