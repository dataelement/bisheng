/** Defaults match the client conversation renderer, not either host's legacy viewer. */
export const CLIENT_MARKDOWN_DEFAULTS = Object.freeze({
  latexParsing: true,
  mobileQuery: '(max-width: 767px)',
  finePointerQuery: '(hover: hover) and (pointer: fine)',
  mathOutput: 'mathml',
  singleDollarTextMath: true,
  highlightDetect: true,
  highlightIgnoreMissing: true,
} as const);
