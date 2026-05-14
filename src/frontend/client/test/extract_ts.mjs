import fs from 'fs';
import path from 'path';
import ts from 'typescript';

const dir = './src/pages/knowledge';
const extracted = new Set();
const instances = [];

function hasChinese(str) {
  return /[\u4e00-\u9fa5]/.test(str);
}

function walkDir(currentPath) {
  const files = fs.readdirSync(currentPath);
  for (const file of files) {
    const fullPath = path.join(currentPath, file);
    const stat = fs.statSync(fullPath);
    if (stat.isDirectory()) {
      walkDir(fullPath);
    } else if (fullPath.endsWith('.ts') || fullPath.endsWith('.tsx')) {
      processFile(fullPath);
    }
  }
}

function processFile(filePath) {
  const code = fs.readFileSync(filePath, 'utf-8');
  const sourceFile = ts.createSourceFile(
    filePath,
    code,
    ts.ScriptTarget.Latest,
    true,
    filePath.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS
  );

  function visit(node) {
    if (ts.isStringLiteral(node)) {
      const parent = node.parent;
      // skip imports
      if (parent && parent.kind === ts.SyntaxKind.ImportDeclaration) return;
      if (parent && parent.kind === ts.SyntaxKind.LiteralType) return;
      
      const text = node.text.trim();
      if (hasChinese(text)) {
        extracted.add(text);
        instances.push({ file: filePath, text, type: 'StringLiteral', start: node.getStart(sourceFile), end: node.getEnd() });
      }
    } else if (ts.isJsxText(node)) {
      const text = node.text.trim();
      if (hasChinese(text)) {
        extracted.add(text);
        instances.push({ file: filePath, text, type: 'JsxText', start: node.getStart(sourceFile), end: node.getEnd() });
      }
    } else if (ts.isTemplateExpression(node) || ts.isNoSubstitutionTemplateLiteral(node)) {
        if (ts.isNoSubstitutionTemplateLiteral(node)) {
            const text = node.text.trim();
            if (hasChinese(text)) {
                extracted.add(text);
                instances.push({ file: filePath, text, type: 'TemplateLiteral', start: node.getStart(sourceFile), end: node.getEnd() });
            }
        } else {
            // TemplateExpression has head and templateSpans
            const headText = node.head.text.trim();
            if (hasChinese(headText)) {
                extracted.add(headText);
            }
            node.templateSpans.forEach(span => {
                const spanText = span.literal.text.trim();
                if (hasChinese(spanText)) {
                    extracted.add(spanText);
                }
            });
            // We just record the whole template expression for replacement later
            // though actual replacement of templates with interpolation is complex.
            // But let's just log it.
            if (hasChinese(node.getText(sourceFile))) {
               instances.push({ file: filePath, text: node.getText(sourceFile), type: 'TemplateExpression', start: node.getStart(sourceFile), end: node.getEnd() });
            }
        }
    }
    ts.forEachChild(node, visit);
  }

  visit(sourceFile);
}

walkDir(dir);

const uniqueArr = Array.from(extracted);
fs.writeFileSync('/tmp/zh_strings_ts.json', JSON.stringify({ unique: uniqueArr, instances }, null, 2));
console.log(`Extracted ${uniqueArr.length} unique Chinese strings using TS AST. Total instances: ${instances.length}`);
