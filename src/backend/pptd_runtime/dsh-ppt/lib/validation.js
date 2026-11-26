import path from 'node:path';

/** Complete diagnostics for the authoring loop; a failed check is not a host failure. */
export const validationSchema = {
  type: 'object', additionalProperties: false,
  properties: {
    status: { type: 'string', required: true, enum: ['pass', 'warning', 'needs_revision'] },
    digest: { type: 'string', required: true },
    pageCount: { type: 'integer', required: true },
    errorCount: { type: 'integer', required: true },
    warningCount: { type: 'integer', required: true },
    issues: {
      type: 'array', required: true,
      items: {
        type: 'object', additionalProperties: false,
        properties: {
          code: { type: 'string', required: true },
          severity: { type: 'string', required: true, enum: ['error', 'warning'] },
          message: { type: 'string', required: true },
          absolutePath: { type: 'string' },
          readArgs: { type: 'object', additionalProperties: false, properties: {
            project_path: { type: 'string', required: true }, file_path: { type: 'string', required: true }
          } },
          file: { type: 'string' }, page: { type: 'integer' }, elementId: { type: 'string' }
        }
      }
    }
  }
};

export function validationReport(check, context = {}) {
  const issues = check.issues.map(issue => {
    if (!issue.file || !context.projectDirectory) return issue;
    const absolutePath = path.resolve(context.projectDirectory, issue.file);
    const relative = path.relative(context.projectDirectory, absolutePath);
    // Invalid project references must never be presented as actionable outside paths.
    if (!relative || relative === '..' || relative.startsWith('..' + path.sep) || path.isAbsolute(relative)) return issue;
    return { ...issue, absolutePath, ...(/\.(page|pptd)$/i.test(relative) && context.projectPath ? {
      readArgs: { project_path: context.projectPath, file_path: relative.split(path.sep).join('/') }
    } : {}) };
  });
  return {
    status: check.status === 'fail' ? 'needs_revision' : check.status,
    digest: check.digest, pageCount: check.pageCount,
    errorCount: check.errorCount, warningCount: check.warningCount,
    issues
  };
}

export function formatValidation(report) {
  const title = report.status === 'needs_revision' ? '校验未通过，需要调整' : report.status === 'warning' ? '校验通过，有建议' : '校验通过';
  const lines = [`${title}：${report.errorCount} 项需要修正，${report.warningCount} 项建议。`];
  const groups = new Map();
  const files = new Map();
  for (const issue of report.issues) {
    if (issue.absolutePath) files.set(issue.absolutePath, issue);
    if (issue.code === 'misplaced-text-style') {
      const key = JSON.stringify([issue.file, issue.page]);
      const group = groups.get(key) ?? { issue, elements: new Set(), fields: new Set(), count: 0 };
      if (issue.elementId !== undefined) group.elements.add(issue.elementId);
      const field = issue.message.match(/^文本属性 (\w+) /)?.[1];
      if (field) group.fields.add(field);
      group.count++;
      groups.set(key, group);
    } else {
      lines.push([
        issue.severity === 'error' ? '需修正' : '建议',
        issue.page === undefined ? '' : `第 ${issue.page} 页`, issue.file ?? '',
        issue.elementId === undefined ? '' : `元素 ${issue.elementId}`,
        `[${issue.code}] ${issue.message}`
      ].filter(Boolean).join(' · '));
    }
  }
  for (const { issue, elements, fields, count } of groups.values()) {
    lines.push(`需修正 · 第 ${issue.page} 页 · ${issue.file} · [misplaced-text-style] ${count} 处文本属性层级错误：将 ${[...fields].join('、')} 移入 content 内，修正 YAML 缩进。涉及元素：${[...elements].join('、') || '未命名元素'}。结构修正后再检查文字溢出。`);
  }
  for (const [absolutePath, issue] of files) {
    lines.push(`文件：${absolutePath}`);
    if (issue.readArgs) lines.push(`读取：pptd_read_file(${JSON.stringify(issue.readArgs)})`);
  }
  if (groups.size) lines.push('同页的文本属性层级错误已合并显示，完整明细保留在 issues 中。');
  if (report.status === 'needs_revision') lines.push('按文件路径和页码定位后修改，再次检查；不同页面可以存在同名元素。');
  return lines.join('\n');
}
