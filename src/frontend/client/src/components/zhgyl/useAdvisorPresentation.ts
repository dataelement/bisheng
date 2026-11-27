import { useEffect, useRef, type RefObject } from 'react';
import { useLocalize } from '~/hooks';
import type { WorkspaceScene } from './scenes';

/** Annotate existing result cells only; do not generate or change business data. */
export function useAdvisorPresentation(scene: WorkspaceScene, container: RefObject<HTMLElement>, conversationId: string) {
  const t = useLocalize();
  const localize = useRef(t);
  localize.current = t;
  useEffect(() => {
    const root = container.current;
    if (!root || !scene || scene === 'select') return;
    let frame = 0;
    const decorate = () => {
      frame = 0;
      root.querySelectorAll<HTMLTableElement>('.bs-mkdown table').forEach(table => {
        const headers = [...table.querySelectorAll('thead th')].map(cell => cell.textContent?.trim() || '');
        const business = scene === 'orders' && headers.some(text => /订单|交付日期|物料|单据号/.test(text)) || headers.some(text => /历史采购单价|历史单价范围|历史单价差额|历史明细数|费用引用|分单号|包装长|费用项目|交付日期|单据号/.test(text));
        if (!business) return;
        const primary = scene === 'procurement' ? headers.some(text => /历史采购单价|历史单价差额/.test(text)) : headers.some(text => /^费用引用$/.test(text));
        table.dataset.assistantTable = primary ? 'primary' : 'detail';
        if (!table.getAttribute('aria-label')) {
          table.setAttribute('aria-label', localize.current(primary ? `zhgyl.tableLabels.${scene}` : 'zhgyl.tableLabels.details'));
          table.dataset.assistantAria = 'true';
        }
        const block = table.closest<HTMLElement>('.bs-mkdown');
        if (block) block.dataset.assistantResult = scene;
        const wrapped = headers.map((text,index) => /^(理由|匹配差异|运输条件及匹配说明|报关条件及匹配说明|推荐理由|推荐说明)$/.test(text) ? index : -1).filter(index => index >= 0);
        const amounts = headers.map((text, index) => /单价|金额|账单总额|历史费用合计/.test(text) ? index : -1).filter(index => index >= 0);
        const numbers = headers.map((text, index) => /数量|净重|毛重|明细数/.test(text) ? index : -1).filter(index => index >= 0);
        table.querySelectorAll('tr').forEach(row => {
          if (row.closest('tbody')) {
            amounts.forEach(index => row.children[index]?.classList.add('assistant-amount'));
            numbers.forEach(index => row.children[index]?.classList.add('assistant-number'));
          }
          if (row.closest('thead')) amounts.forEach(index => row.children[index]?.classList.add('assistant-amount-heading'));
          if (row.closest('tbody')) wrapped.forEach(index => row.children[index]?.setAttribute('data-zh-wrap', 'true'));
        });
      });
      if (scene === 'customs') root.querySelectorAll<HTMLElement>('.bs-mkdown[data-assistant-result]').forEach(block => {
        const tables = block.querySelectorAll('table');
        const primary = block.querySelector('table[data-assistant-table="primary"]');
        const shared = tables.length === 1 && primary ? [...primary.querySelectorAll('tbody tr')].map(row => [...row.children].map(cell => cell.textContent || '')).filter(cells => /^F[0-9]+$/.test(cells[0] || '') && /共享账单总额，未分摊/.test(cells[5] || '')) : [];
        const text = shared.length ? localize.current('zhgyl.sharedFeeHint') + shared.map(cells => `${cells[0]}：${cells[5]}`).join('；') + '。' : '';
        let note = block.querySelector<HTMLElement>('[data-assistant-shared-summary]');
        if (text) {
          if (!note) { note = document.createElement('p'); note.dataset.assistantSharedSummary = 'true'; note.dataset.assistantNote = 'warning'; block.append(note); }
          if (note.textContent !== text) note.textContent = text;
        } else note?.remove();
      });
      root.querySelectorAll('.bs-mkdown p').forEach(paragraph => {
        const text = paragraph.textContent || '';
        if (/^(来源：|数据来源：)/.test(text)) paragraph.setAttribute('data-assistant-note', 'source');
        if (/共享账单总额，未分摊|弱匹配提示/.test(text)) paragraph.setAttribute('data-assistant-note', 'warning');
      });
    };
    const observer = new MutationObserver(() => { if (!frame) frame = requestAnimationFrame(decorate); });
    observer.observe(root, { childList: true, subtree: true, characterData: true });
    decorate();
    return () => {
      observer.disconnect();
      if (frame) cancelAnimationFrame(frame);
      root.querySelectorAll('[data-assistant-shared-summary]').forEach(note => note.remove());
      root.querySelectorAll<HTMLElement>('[data-assistant-aria]').forEach(table => { table.removeAttribute('aria-label'); delete table.dataset.assistantAria; });
      root.querySelectorAll('[data-assistant-table]').forEach(table => table.removeAttribute('data-assistant-table'));
      root.querySelectorAll('[data-assistant-result]').forEach(block => block.removeAttribute('data-assistant-result'));
      root.querySelectorAll('[data-zh-wrap]').forEach(cell => cell.removeAttribute('data-zh-wrap'));
      root.querySelectorAll('[data-assistant-note]').forEach(note => note.removeAttribute('data-assistant-note'));
      root.querySelectorAll('.assistant-amount,.assistant-number,.assistant-amount-heading').forEach(cell => cell.classList.remove('assistant-amount', 'assistant-number', 'assistant-amount-heading'));
    };
  }, [scene, container, conversationId]);
}
