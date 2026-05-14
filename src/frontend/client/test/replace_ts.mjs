import fs from 'fs';
import path from 'path';
import ts from 'typescript';

const mapData = JSON.parse(fs.readFileSync('/tmp/zh_map.json', 'utf8'));

const dir = './src/pages/knowledge';

function hasChinese(str) {
  return /[\u4e00-\u9fa5]/.test(str);
}

const unmapped = new Set();

function escapeRegExp(string) {
  return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); // $& means the whole matched string
}

function processFile(filePath) {
  const code = fs.readFileSync(filePath, 'utf-8');
  if (!hasChinese(code)) return; // No Chinese, skip
  
  const sourceFile = ts.createSourceFile(
    filePath,
    code,
    ts.ScriptTarget.Latest,
    true,
    filePath.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS
  );

  const replacements = [];
  let componentStart = -1;
  let componentBlockStart = -1;

  function visit(node) {
    // Function / ArrowFunction detection for hook injection
    if (ts.isFunctionDeclaration(node) || ts.isArrowFunction(node) || ts.isFunctionExpression(node)) {
      // Very basic heuristic: if it contains JSX, it's a component
      let hasJsx = false;
      function checkJsx(n) {
        if (ts.isJsxElement(n) || ts.isJsxSelfClosingElement(n) || ts.isJsxFragment(n)) hasJsx = true;
        if (!hasJsx) ts.forEachChild(n, checkJsx);
      }
      checkJsx(node);
      if (hasJsx && node.body && ts.isBlock(node.body)) {
         // It's a React Component
         const statements = node.body.statements;
         let hasLocalize = false;
         statements.forEach(stmt => {
            if (stmt.getText(sourceFile).includes('useLocalize')) hasLocalize = true;
         });
         
         if (!hasLocalize) {
            // Find insertion point
            if (componentBlockStart === -1 || node.getStart(sourceFile) < componentStart) {
                componentStart = node.getStart(sourceFile);
                componentBlockStart = statements.length > 0 ? statements[0].getStart(sourceFile) : node.body.getEnd() - 1;
            }
         }
      }
    }

    if (ts.isStringLiteral(node)) {
      const parent = node.parent;
      if (parent && parent.kind === ts.SyntaxKind.ImportDeclaration) return;
      if (parent && parent.kind === ts.SyntaxKind.LiteralType) return;
      
      const text = node.text;
      if (hasChinese(text)) {
        let entry = mapData[text.trim()];
        if (entry) {
          let replacement = `localize("${'com_knowledge.' + entry.key}")`;
          if (parent.kind === ts.SyntaxKind.JsxAttribute) {
             replacement = `{${replacement}}`;
          }
          if (parent.kind === ts.SyntaxKind.PropertyAssignment && !text.includes('localize')) {
             // e.g. title: "中文" -> title: localize(...)
          }
          replacements.push({ start: node.getStart(sourceFile), end: node.getEnd(), text: replacement });
        } else {
          unmapped.add(text);
        }
      }
    } else if (ts.isJsxText(node)) {
      const text = node.text;
      if (hasChinese(text)) {
        let entry = mapData[text.trim()];
        if (entry) {
          let replacement = `{localize("${'com_knowledge.' + entry.key}")}`;
          replacements.push({ start: node.getStart(sourceFile), end: node.getEnd(), text: replacement });
        } else {
          unmapped.add(text.trim());
        }
      }
    } else if (ts.isNoSubstitutionTemplateLiteral(node)) {
        const text = node.text;
        if (hasChinese(text)) {
            let entry = mapData[text.trim()];
            if (entry) {
              let replacement = `localize("${'com_knowledge.' + entry.key}")`;
              if (node.parent && node.parent.kind === ts.SyntaxKind.JsxAttribute) {
                 replacement = `{${replacement}}`;
              }
              replacements.push({ start: node.getStart(sourceFile), end: node.getEnd(), text: replacement });
            } else {
                unmapped.add(text.trim());
            }
        }
    } else if (ts.isTemplateExpression(node)) {
        const fullText = node.getText(sourceFile);
        if (hasChinese(fullText)) {
            // Very naive way to process simple template strings if mapped
            const stripped = fullText.replace(/^[`'"]|[`'"]$/g, '');
            let entry = mapData[stripped];
            if (entry) {
                let replacement = `localize("${'com_knowledge.' + entry.key}")`;
                // Add interpolation if needed, but since our map generation didn't cover dynamic args well,
                // we'll just log an error or unmapped for now. Wait, I didn't map template expressions to args. 
                // So if it's not mapped exactly, we add to unmapped.
                unmapped.add(stripped);
            } else {
                unmapped.add(stripped);
            }
        }
    }
    
    // We only traverse strings explicitly, avoiding nested string overlaps
    ts.forEachChild(node, visit);
  }

  visit(sourceFile);

  if (replacements.length > 0) {
    // Check if useLocalize needs to be imported
    let hasLocalizeImport = code.includes('useLocalize');
    let modifiedCode = code;
    
    replacements.sort((a, b) => b.start - a.start);
    
    // Inject useLocalize hook if we found a component block and it's not there
    if (!code.includes('const localize = useLocalize()') && componentBlockStart !== -1) {
        replacements.push({ start: componentBlockStart, end: componentBlockStart, text: `const localize = useLocalize();\n  ` });
    }
    
    // Add import if needed
    if (!hasLocalizeImport) {
        // Find last import decl
        let lastImportEnd = 0;
        ts.forEachChild(sourceFile, n => {
           if (ts.isImportDeclaration(n)) {
               lastImportEnd = Math.max(lastImportEnd, n.getEnd());
           }
        });
        if (lastImportEnd > 0) {
             replacements.push({ start: lastImportEnd, end: lastImportEnd, text: `\nimport { useLocalize } from "~/hooks";` });
        } else {
             replacements.push({ start: 0, end: 0, text: `import { useLocalize } from "~/hooks";\n` });
        }
    }

    // Sort again
    replacements.sort((a, b) => b.start - a.start);

    for (const r of replacements) {
       modifiedCode = modifiedCode.slice(0, r.start) + r.text + modifiedCode.slice(r.end);
    }
    
    fs.writeFileSync(filePath, modifiedCode, 'utf-8');
    console.log(`Updated ${filePath}`);
  }
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

walkDir(dir);

if (unmapped.size > 0) {
    console.log(`Warning: ${unmapped.size} strings were not replaced because they were missing from map or complex:`, Array.from(unmapped));
}
