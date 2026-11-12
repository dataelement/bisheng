/** Text values contain real line breaks; literal escape notation requires explicit intent. */
export function containsLiteralLineBreak(text) {
  return typeof text === 'string' && /\\[nr]/u.test(text.replace(/<[^>]+>/gu, ''));
}

/** Return content diagnostics shared by the CLI and host before layout/export. */
export function textEscapeIssues(content, field = 'content') {
  if (content === undefined || content === null) return [];
  if (content.literalEscapes !== undefined && typeof content.literalEscapes !== 'boolean') {
    return [{ code: 'text-literal-escapes', severity: 'error', message: `${field}.literalEscapes 使用布尔值；需要原样展示转义语法或路径时设为 true。` }];
  }
  if (content.literalEscapes === true || !containsLiteralLineBreak(content.text)) return [];
  return [{
    code: 'text-escaped-newline', severity: 'error',
    message: `${field}.text 含字面量 \\n 或 \\r。多行正文使用 YAML |- 加实际换行，修正后重新检查文本框容量。原样展示代码、转义语法或路径时，在 ${field} 内设置 literalEscapes: true。`,
  }];
}
