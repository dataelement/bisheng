#!/usr/bin/env node

/**
 * Check for case-sensitive import path mismatches.
 *
 * On macOS / Windows the filesystem is case-insensitive, so
 * `import { Foo } from './ArticleList/Bar'` resolves even when the real
 * directory is `articleList`. On Linux CI/CD this causes a build failure.
 *
 * This script uses `git ls-files` (whose index is ALWAYS case-sensitive)
 * to build a lookup of real directory names, then scans every source file
 * for relative imports and checks each DIRECTORY segment against the git index.
 *
 * Usage:
 *   node scripts/check-case-sensitive-imports.mjs
 *
 * Exit code:
 *   0 - all imports match
 *   1 - at least one mismatch was found
 */

import { execSync } from 'child_process';
import fs from 'fs';
import path from 'path';

const ROOT = path.resolve(process.cwd());

// ── 1. Build a case-insensitive -> case-correct directory map from git ──
const gitFiles = execSync('git ls-files', { cwd: ROOT, encoding: 'utf-8' })
  .split('\n')
  .filter(Boolean);

// Map: lowercase directory path -> actual cased directory path
// e.g. "src/pages/subscription/articlelist" -> "src/pages/Subscription/articleList"
const dirCaseMap = new Map();
// Map: lowercase file path (without extension) -> actual cased file path
const fileCaseMap = new Map();

for (const f of gitFiles) {
  const parts = f.split('/');

  // Record every directory prefix
  for (let i = 1; i < parts.length; i++) {
    const dirPath = parts.slice(0, i).join('/');
    dirCaseMap.set(dirPath.toLowerCase(), dirPath);
  }

  // Record file path (strip common extensions for matching bare imports)
  fileCaseMap.set(f.toLowerCase(), f);
  // Also store without extension for bare imports like './Foo' -> './Foo.tsx'
  const withoutExt = f.replace(/\.(ts|tsx|js|jsx|json|css|scss)$/, '');
  fileCaseMap.set(withoutExt.toLowerCase(), withoutExt);
}

// ── 2. Scan source files for relative imports ───────────────────────
const importRegex = /(?:from\s+['"]|require\s*\(\s*['"])(\.\.?\/[^'"]+)['"]/g;

const sourceFiles = gitFiles.filter(
  (f) => f.startsWith('src/') && /\.(ts|tsx|js|jsx)$/.test(f)
);

let errorCount = 0;

for (const relFile of sourceFiles) {
  const absFile = path.join(ROOT, relFile);
  if (!fs.existsSync(absFile)) continue;

  const content = fs.readFileSync(absFile, 'utf-8');
  const fileDir = path.dirname(relFile);

  let match;
  importRegex.lastIndex = 0;
  while ((match = importRegex.exec(content)) !== null) {
    const rawImport = match[1]; // e.g. "./ArticleList/ArticleCard"

    // Resolve to a path relative to ROOT
    const resolved = path.posix.normalize(path.posix.join(fileDir, rawImport));
    const resolvedParts = resolved.split('/');

    // Check each DIRECTORY segment of the import path
    for (let i = 1; i < resolvedParts.length; i++) {
      const dirPath = resolvedParts.slice(0, i).join('/');
      const dirLower = dirPath.toLowerCase();

      if (!dirCaseMap.has(dirLower)) continue; // Not tracked by git

      const realDir = dirCaseMap.get(dirLower);
      if (dirPath !== realDir) {
        const line = content.substring(0, match.index).split('\n').length;
        const importSegment = resolvedParts[i - 1];
        const realSegment = realDir.split('/').pop();
        console.error(
          `\x1b[31m✗ Case mismatch\x1b[0m in \x1b[36m${relFile}:${line}\x1b[0m`
        );
        console.error(
          `  Directory segment: \x1b[33m${importSegment}\x1b[0m -> should be \x1b[32m${realSegment}\x1b[0m`
        );
        console.error(
          `  Full import: "${rawImport}"`
        );
        console.error();
        errorCount++;
        break; // Only report first mismatch per import
      }
    }

    // Also check the final file segment (the basename) if it resolves to a file
    const resolvedLower = resolved.toLowerCase();
    if (fileCaseMap.has(resolvedLower)) {
      const realFile = fileCaseMap.get(resolvedLower);
      // Compare only the parts that are in the import (without auto-added extension)
      const realParts = realFile.split('/');
      for (let i = 0; i < resolvedParts.length && i < realParts.length; i++) {
        if (resolvedParts[i] !== realParts[i]) {
          const line = content.substring(0, match.index).split('\n').length;
          console.error(
            `\x1b[31m✗ Case mismatch\x1b[0m in \x1b[36m${relFile}:${line}\x1b[0m`
          );
          console.error(
            `  Segment: \x1b[33m${resolvedParts[i]}\x1b[0m -> should be \x1b[32m${realParts[i]}\x1b[0m`
          );
          console.error(
            `  Full import: "${rawImport}"`
          );
          console.error();
          errorCount++;
          break;
        }
      }
    }
  }
}

if (errorCount > 0) {
  console.error(
    `\x1b[31m✗ Found ${errorCount} case-sensitive import mismatch(es).\x1b[0m`
  );
  console.error(
    `  These will cause build failures on Linux. Please fix the import casing.`
  );
  process.exit(1);
} else {
  console.log('\x1b[32m✓ All import paths match git index casing.\x1b[0m');
  process.exit(0);
}
