/** Preserve Latin word boundaries while allowing CJK and oversized tokens to wrap. */
export function wrapTextLines(text, width, measure, wrap = true) {
  if (!wrap || width <= 0) return text.split('\n');
  return text.split('\n').flatMap(paragraph => {
    const lines = [];
    let current = '';
    const flush = () => { if (current.trim()) lines.push(current.trimEnd()); current = ''; };
    for (const token of paragraph.match(/[A-Za-z0-9]+(?:[’'/-][A-Za-z0-9]+)*[.,:;!?]?|\s+|./gu) ?? []) {
      if (/^\s+$/u.test(token)) { if (current) current += token; continue; }
      if (current && measure(current + token) > width) flush();
      if (measure(token) <= width) current += token;
      else for (const character of token) {
        if (current && measure(current + character) > width) flush();
        current += character;
      }
    }
    flush();
    return lines.length ? lines : [''];
  });
}
