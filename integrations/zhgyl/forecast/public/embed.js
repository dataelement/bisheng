/* Presentation bridge: replay one saved service result, never recalculate it. */
(() => {
  'use strict';
  const params = new URLSearchParams(location.search);
  const embedded = params.get('embed') === '1';
  if (embedded) document.documentElement.dataset.embedded = 'true';
  const style = document.createElement('link'); style.rel='stylesheet'; style.href=new URL('embed.css',document.baseURI).href; document.head.append(style);
  const view = params.get('view');
  if (!view) return;
  document.documentElement.dataset.resultOnly = 'true';
  document.addEventListener('DOMContentLoaded', async () => {
    const status = document.getElementById('status');
    const skip = document.querySelector('.skip-link');
    if (skip) { skip.href='#result'; skip.textContent='跳转至预测结果'; }
    const fail = message => {
      document.documentElement.dataset.resultOnly = 'false';
      status.textContent = message;
      status.setAttribute('role', 'alert');
    };
    if (!/^[a-f0-9]{32}$/.test(view)) { fail('结果链接无效，请重新选择报告。'); return; }
    try {
      if (!window.ForecastView) throw new Error('预测展示模块未加载');
      await window.ForecastView.ready;
      const response = await fetch(new URL(`api/reports/${view}/result.json`,document.baseURI), {credentials:'same-origin'});
      if (!response.ok) throw new Error('保存的结果不可用，请重新分析');
      const data = await response.json();
      if (data.request_id !== view || !['predicted','mixed','unpredictable','no_history'].includes(data.status)) {
        throw new Error('结果标识或状态不匹配');
      }
      const scope = data.scope || {};
      const assign = (id, value) => {
        if (value == null) return;
        const field = document.getElementById(id);
        if (field.tagName === 'SELECT' && ![...field.options].some(o=>o.value===String(value))) {
          const option = document.createElement('option'); option.value=String(value); option.textContent=String(value); field.append(option);
        }
        field.value = String(value);
      };
      assign('spec', scope.specs?.length === 1 ? scope.specs[0] : 'all');
      assign('customer', scope.customer || data.customer);
      assign('start-month', scope.start_month || data.period?.start_month);
      assign('months', scope.months || data.period?.months);
      document.getElementById('welcome').hidden = true;
      window.ForecastView.showResult(data);
      const bar = document.createElement('div'); bar.className = 'embed-toolbar';
      const label = document.createElement('span'); label.textContent='采购需求预测 · 模拟结果';
      const toggle = document.createElement('button'); toggle.type='button'; toggle.textContent='调整预测范围';
      toggle.setAttribute('aria-expanded','false');
      toggle.addEventListener('click', () => {
        const open = document.documentElement.dataset.resultOnly === 'true';
        document.documentElement.dataset.resultOnly = String(!open);
        toggle.textContent = open ? '收起查询条件' : '调整预测范围';
        toggle.setAttribute('aria-expanded', String(open));
        if (open) document.getElementById('query').focus();
      });
      bar.append(label,toggle); document.querySelector('.page-shell').prepend(bar);
      document.documentElement.dataset.viewRequest = data.request_id;
    } catch (error) { fail(`结果读取失败：${error.message}。`); }
  }, {once:true});
})();
