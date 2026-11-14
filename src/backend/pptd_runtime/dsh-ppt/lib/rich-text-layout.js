/** Shared text geometry for validation and previews, using each run's effective style. */
const positive = (value, fallback) => Number.isFinite(value) && value > 0 ? value : fallback;
const finite = value => Number.isFinite(value) ? value : 0;
function glyphWidth(character) {
  if (/\p{Mark}/u.test(character)) return 0;
  if (/\s/u.test(character)) return .33;
  if (/^[ilI1|.,'`:;!]$/u.test(character)) return .3;
  if (/^[mwMW@%&]$/u.test(character)) return .82;
  if (/^[A-Z]$/u.test(character)) return .68;
  if (/^[\u0000-\u00ff]$/u.test(character)) return .56;
  return 1;
}

function measureRichText(runs, style, width, height) {
  // Wrapped lines reserve a small margin when choosing a break. A no-wrap line uses its full box.
  const availableLineWidth = Math.max(0, width) * (style.wrap === false || style.authored ? 1 : .95);
  const base = { ...style, fontSize: positive(style.fontSize, 18), lineHeight: positive(style.lineHeight, 1.15) };
  const characters = runs.flatMap(run => {
    const options = { ...base, ...run.options };
    options.fontSize = positive(options.fontSize, base.fontSize);
    return Array.from(run.text, character => ({ character, options }));
  });
  const measure = chars => chars.reduce((sum, item, i) => sum + glyphWidth(item.character) * item.options.fontSize * (item.options.bold && !style.authored ? 1.04 : 1) + (i ? finite(item.options.letterSpacing) : 0), 0);
  const lines = [];
  let current = [], offset = 0, emptyStyle = base, paragraphWidth = 0, widestLine = 0;
  const flush = (trim = false) => {
    if (trim) while (current.length && /\s/u.test(current.at(-1).character)) current.pop();
    const segments = [];
    for (const item of current) {
      const last = segments.at(-1);
      if (last?.options === item.options) last.text += item.character;
      else segments.push({ text: item.character, options: item.options });
    }
    const fontSize = Math.max(...(current.length ? current.map(item => item.options.fontSize) : [emptyStyle.fontSize]));
    const lineHeight = Math.max(...(current.length ? current.map(item => item.options.fontSize * positive(item.options.lineHeight, base.lineHeight)) : [emptyStyle.fontSize * base.lineHeight]));
    lines.push({ runs: segments, width: measure(current), height: lineHeight, fontSize });
    current = [];
  };
  const text = characters.map(item => item.character).join('');
  for (const match of text.matchAll(/\n|[A-Za-z0-9]+(?:[’'/-][A-Za-z0-9]+)*[.,:;!?]?|[^\S\n]+|./gu)) {
    const length = Array.from(match[0]).length;
    const token = characters.slice(offset, offset += length);
    if (match[0] === '\n') {
      flush(); widestLine = Math.max(widestLine, paragraphWidth); paragraphWidth = 0;
      emptyStyle = token[0].options;
      continue;
    }
    paragraphWidth += measure(token);
    if (style.wrap !== false && availableLineWidth > 0 && !/^\s+$/u.test(match[0])) {
      if (current.length && measure([...current, ...token]) > availableLineWidth) flush(true);
      if (measure(token) > availableLineWidth) {
        for (const item of token) {
          if (current.length && measure([...current, item]) > availableLineWidth) flush(true);
          current.push(item);
        }
        continue;
      }
    }
    current.push(...token);
  }
  if (current.length || text.endsWith('\n')) flush();
  widestLine = Math.max(widestLine, paragraphWidth, ...lines.map(line => line.width));
  const requiredHeight = lines.reduce((sum, line) => sum + line.height, 0);
  const availableHeight = Math.max(0, height);
  const horizontalOverflow = lines.some(line => line.width > availableLineWidth + .01);
  let used = 0;
  const maxLineCount = lines.filter(line => (used += line.height) <= availableHeight + .01).length;
  return { lines, lineCount: lines.length, maxLineCount, requiredHeight, availableHeight,
    availableLineWidth, widestLine, horizontalOverflow,
    overflow: horizontalOverflow || requiredHeight > availableHeight + .01 };
}

export function scaleTextRuns(runs, scale) {
  return runs.map(run => ({ ...run, options: { ...run.options,
    ...(Number.isFinite(run.options?.fontSize) ? { fontSize: run.options.fontSize * scale } : {}) } }));
}

/** Honor the source's explicit shrink-to-fit setting with identical preview/export metrics. */
export function layoutRichText(runs, style, width, height) {
  const original = measureRichText(runs, style, width, height);
  if (style.fit !== 'shrink' || !original.overflow || width <= 0 || height <= 0) return { ...original, fontScale: 1 };
  let lower = .001, upper = 1;
  const measure = scale => measureRichText(scaleTextRuns(runs, scale), { ...style, fontSize: positive(style.fontSize, 18) * scale }, width, height);
  for (let i = 0; i < 16; i++) {
    const middle = (lower + upper) / 2;
    if (measure(middle).overflow) upper = middle;
    else lower = middle;
  }
  return { ...measure(lower), fontScale: lower };
}
