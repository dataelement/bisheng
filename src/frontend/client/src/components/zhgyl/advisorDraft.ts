/** Select an existing editable placeholder after filling a draft; never submit it. */
export function selectAdvisorPlaceholder(scene: string) {
  const editor = document.querySelector<HTMLElement>(`[data-assistant-scene="${scene}"] [data-testid="ai-chat-input"]`);
  if (!editor) return;
  editor.focus();
  const walker = document.createTreeWalker(editor, NodeFilter.SHOW_TEXT);
  const nodes: { node: Node; start: number }[] = [];
  let node: Node | null;
  let all = '';
  while ((node = walker.nextNode())) {
    if (node.parentElement?.closest('[contenteditable="false"]')) continue;
    nodes.push({ node, start: all.length });
    all += node.textContent || '';
  }
  const start = all.indexOf('\u3010');
  const end = all.indexOf('\u3011', start);
  if (start < 0 || end < start) return;
  const a = nodes.filter(item => item.start <= start).pop();
  const b = nodes.filter(item => item.start <= end).pop();
  if (!a || !b) return;
  const range = document.createRange();
  range.setStart(a.node, start - a.start); range.setEnd(b.node, end - b.start + 1);
  const selection = window.getSelection();
  selection?.removeAllRanges(); selection?.addRange(range);
}
