/* Explicit mount into a caller-selected D workspace. No global DOM scans,
 * chat interception, credentials, model calls, or persistent environment writes. */
(() => {
  'use strict';
  window.ForecastWorkspace = Object.freeze({
    mount(container, {baseUrl, requestId, preview=true} = {}) {
      if (!(container instanceof HTMLElement)) throw new Error('需要明确的工作区容器');
      if (!/^[a-f0-9]{32}$/.test(requestId || '')) throw new Error('无效结果编号');
      const base = new URL(baseUrl, location.href);
      if (!['http:','https:'].includes(base.protocol) || base.username || base.password || base.search || base.hash) throw new Error('无效展示服务地址');
      if (!['127.0.0.1','localhost'].includes(base.hostname) && base.origin !== location.origin) throw new Error('需使用同源服务或本机预览');
      if (container.dataset.forecastMounted) throw new Error('工作区已挂载预测展示');
      const before = document.createDocumentFragment();
      while(container.firstChild) before.append(container.firstChild);
      const oldStyle = container.getAttribute('style');
      container.dataset.forecastMounted='true';
      Object.assign(container.style,{display:'flex',flexDirection:'column',overflow:'hidden',padding:'0',minHeight:'0'});
      const label=document.createElement('div');
      label.style.cssText='flex:none;display:flex;align-items:center;justify-content:space-between;gap:12px;padding:9px 12px;background:#edf4fc;border-bottom:1px solid #d6e3f1;font:11px/1.7 "PingFang SC",sans-serif;color:#416581';
      const text=document.createElement('span');text.textContent=preview?'本地适配预览 · API与数据模拟 · 刷新恢复D原界面':'采购需求预测 · 模拟演示';
      const close=document.createElement('button');close.type='button';close.textContent='退出预览';close.style.cssText='flex:none;border:1px solid #c3d6e8;border-radius:5px;background:white;color:#365d82;padding:4px 8px;cursor:pointer';
      const frame=document.createElement('iframe');frame.title='采购需求预测工作区';
      frame.style.cssText='display:block;flex:1;width:100%;min-width:0;min-height:0;border:0;background:#f5f8fc';
      frame.setAttribute('sandbox','allow-scripts allow-same-origin allow-forms allow-downloads allow-popups allow-popups-to-escape-sandbox');
      frame.referrerPolicy='no-referrer';
      base.searchParams.set('embed','1');base.searchParams.set('view',requestId);frame.src=base.href;
      label.append(text,close);container.append(label,frame);
      let destroyed=false;
      const destroy=()=>{if(destroyed)return;destroyed=true;container.replaceChildren(before);delete container.dataset.forecastMounted;if(oldStyle==null)container.removeAttribute('style');else container.setAttribute('style',oldStyle);};
      close.addEventListener('click',destroy);
      return Object.freeze({frame,destroy});
    }
  });
})();
