import { readdirSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, it } from 'vitest';

it('keeps production primitive imports on the shared library without compatibility entry points', () => {
    const violations: string[] = [];
    function scan(directory: string) {
        for (const entry of readdirSync(directory, { withFileTypes: true })) {
            const file = resolve(directory, entry.name);
            if (entry.isDirectory()) { if (entry.name !== 'test') scan(file); }
            else if (/\.tsx?$/.test(file) && !file.includes('.test.')) {
                const source = readFileSync(file, 'utf8');
                if (/from\s+['"][^'"]*bs-ui\/(?:(?:button|input)(?:\/index)?|toast(?:\/use-toast)?)['"]/.test(source)) violations.push(file);
            }
        }
    }
    scan(resolve(process.cwd(), 'src'));
    expect(violations).toEqual([]);
});
