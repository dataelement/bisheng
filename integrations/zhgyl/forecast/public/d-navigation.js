/* D sidebar module. Reuses the native router and isolates this feature's view. */
(() => {
  'use strict';
  if (window.__procurementForecastNavigation) return;
  window.__procurementForecastNavigation = true;
  const route = '/workspace/c/new?module=procurement-forecast';
  const app = '/workspace/procurement-forecast/?embed=1';
  const hidden = new Map();
  let scheduled = false;
  const style = document.createElement('style');
  style.id = 'procurement-forecast-navigation-style';
  const paletteKeys=['--aviation-page','--aviation-sidebar','--aviation-surface','--aviation-border','--aviation-hero-border','--aviation-input-border','--aviation-input-focus','--aviation-title','--aviation-hero-light'];
  function applyPalette(frame) {
    const target=frame.contentDocument?.documentElement;if(!target)return;
    const source=getComputedStyle(document.documentElement);
    for(const key of paletteKeys){const value=source.getPropertyValue(key).trim();if(value)target.style.setProperty(key,value);}
  }
  style.textContent = `
    body.zh-forecast-open #root aside{background:var(--aviation-sidebar,#eaf0f2)!important;border-right-color:var(--aviation-border,#dbe4e8)!important}
    #procurement-forecast-navigation.zh-forecast-entry{display:flex!important}
    #procurement-forecast-navigation[aria-current="page"]{background:#dfeaf5!important;color:#1f5d95!important;font-weight:600}
    .zh-forecast-entry:focus-visible{outline:2px solid #447db0;outline-offset:2px}
    #procurement-forecast-module{display:flex;flex:1 1 0;flex-direction:column;min-width:0;min-height:0;height:100%;background:var(--aviation-page,#f5f8fc)}
    #procurement-forecast-module>iframe{display:block;width:100%;height:100%;flex:1 1 0;min-height:0;border:0;background:var(--aviation-page,#f5f8fc)}
    .zh-forecast-load-error{padding:24px;color:#526b80;font:14px/1.8 "PingFang SC",sans-serif}
  `;
  document.head.append(style);
  function active() {
    return location.pathname === '/workspace/c/new' && new URLSearchParams(location.search).get('module') === 'procurement-forecast';
  }
  function schedule() {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(() => { scheduled=false; sync(); });
  }
  function addNavigation(source) {
    let link = document.getElementById('procurement-forecast-navigation');
    if (link) return link;
    link=document.createElement('a');link.id='procurement-forecast-navigation';
    link.className=source.className.replace(/\b(active|zh-orders-entry)\b/g,'')+' zh-forecast-entry';
    link.href=route;link.title='采购需求预测';link.setAttribute('aria-label','采购需求预测');link.dataset.testid='forecast-navigation-link';
    link.innerHTML='<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M4 4v16h16M7 14l4-5 4 3 5-7M16 5h4v4"/></svg><span class="min-w-0 flex-1 truncate py-px">采购需求预测</span>';
    link.addEventListener('click', event => {
      if (event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const detail={path:route,handled:false};
      window.dispatchEvent(new CustomEvent('zh:sidebar-navigate',{detail}));
      if (detail.handled) event.preventDefault();
      schedule();
    });
    source.after(link);
    return link;
  }
  function restore() {
    document.body.classList.remove('zh-forecast-open');
    document.getElementById('procurement-forecast-module')?.remove();
    for (const [node,display] of hidden) if (node.isConnected) node.style.display=display;
    hidden.clear();
  }
  function sync() {
    const source=document.querySelector('a.zh-orders-entry');
    // Wait for the actual authenticated D sidebar, never build a substitute shell.
    if (!source) { restore(); return; }
    const link=addNavigation(source), selected=active();
    link.classList.toggle('active',selected);
    if (selected) link.setAttribute('aria-current','page'); else link.removeAttribute('aria-current');
    if (!selected) { restore(); return; }
    document.body.classList.add('zh-forecast-open');
    const surface=document.querySelector('.dsh-chat-surface');
    if (!surface || !surface.parentElement) return;
    if (!hidden.has(surface)) hidden.set(surface,surface.style.display);
    if (surface.style.display!=='none') surface.style.display='none';
    let host=document.getElementById('procurement-forecast-module');
    if (host && host.parentElement===surface.parentElement) return;
    host?.remove();host=document.createElement('section');host.id='procurement-forecast-module';host.setAttribute('aria-label','采购需求预测');
    const frame=document.createElement('iframe');frame.id='procurement-forecast-frame';frame.title='采购需求预测工作台';
    frame.referrerPolicy='same-origin';
    frame.setAttribute('sandbox','allow-scripts allow-same-origin allow-forms allow-downloads allow-popups allow-popups-to-escape-sandbox');
    frame.src=app;
    frame.addEventListener('load',()=>{
      try {
        if(frame.contentDocument?.querySelector('#query-form')){applyPalette(frame);return;}
      } catch (_) {}
      const error=document.createElement('div');error.className='zh-forecast-load-error';error.setAttribute('role','alert');
      error.textContent='预测页面暂时无法加载。';const retry=document.createElement('a');retry.href=route;retry.textContent='重新打开';error.append(' ',retry);host.replaceChildren(error);
    },{once:true});
    host.append(frame);surface.parentElement.insertBefore(host,surface);
  }
  new MutationObserver(changes=>{
    if(changes.some(change=>!change.target.closest?.('#procurement-forecast-module,.zh-forecast-entry')))schedule();
  }).observe(document.documentElement,{childList:true,subtree:true});
  window.addEventListener('popstate',schedule);
  window.addEventListener('zh:sidebar-navigate',schedule);
  document.addEventListener('click',event=>{
    if(event.target.closest?.('a[href^="/workspace/"]'))schedule();
  },true);
  schedule();
})();
