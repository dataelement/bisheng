import { File } from 'node:buffer';
import JSZip from 'jszip';
import 'fake-indexeddb/auto';
import { parseSkillFile } from '../parseSkill';
import { changePersonalSkill, listPersonalSkills } from '../skillPreviewStore';

const markdown = (name = 'weekly-report') => `---\nname: ${name}\ndescription: Produce a weekly report.\n---\nRead the sources and summarize the week.`;
const file = (content: string | Uint8Array, name = 'SKILL.md') => new File([content], name) as unknown as globalThis.File;
async function archive(entries: Record<string, string>, name = 'report.zip') {
  const zip = new JSZip();
  for (const [path, content] of Object.entries(entries)) zip.file(path, content);
  return file(await zip.generateAsync({ type: 'uint8array' }), name);
}

describe('skill package validation', () => {
  it('extracts a UTF-8 manifest without executing the instructions', async () => {
    const result = await parseSkillFile(file(markdown()));
    expect(result.name).toBe('weekly-report');
    expect(result.files).toEqual(['SKILL.md']);
    expect(result.instructions).toContain('Read the sources');
  });
  it('supports a packaged skill and preserves its resources', async () => {
    const result = await parseSkillFile(await archive({ 'report/SKILL.md': markdown(), 'report/assets/data.csv': 'a,b' }, 'report.skill'));
    expect(result.files).toEqual(['report/SKILL.md', 'report/assets/data.csv']);
  });
  it.each([
    ['missing YAML', 'plain instructions', 'manifest'],
    ['invalid identifier', markdown('Bad Name'), 'name'],
    ['empty instructions', '---\nname: report\ndescription: Test\n---', 'manifest'],
    ['duplicate metadata', '---\nname: one\nname: two\ndescription: Test\n---\nText', 'manifest'],
  ])('rejects %s', async (_label, text, code) => {
    await expect(parseSkillFile(file(text))).rejects.toMatchObject({ code });
  });
  it('rejects a renamed non-ZIP file', async () => {
    await expect(parseSkillFile(file('not a zip', 'report.skill'))).rejects.toMatchObject({ code: 'archive' });
  });
  it('rejects missing and multiple manifests', async () => {
    await expect(parseSkillFile(await archive({ 'README.md': markdown() }))).rejects.toMatchObject({ code: 'manifest_count' });
    await expect(parseSkillFile(await archive({ 'a/SKILL.md': markdown(), 'b/SKILL.md': markdown() }))).rejects.toMatchObject({ code: 'manifest_count' });
  });
  it('rejects traversal before JSZip normalized names can hide it', async () => {
    await expect(parseSkillFile(await archive({ '../SKILL.md': markdown() }))).rejects.toMatchObject({ code: 'archive_path' });
  });
  it('caps actual manifest output even when its compressed size is small', async () => {
    const zip = new JSZip().file('SKILL.md', markdown() + 'x'.repeat(1024 * 1024));
    const input = file(await zip.generateAsync({ type: 'uint8array', compression: 'DEFLATE' }), 'report.zip');
    await expect(parseSkillFile(input)).rejects.toMatchObject({ code: 'manifest_size' });
  });
  it('rejects unsupported, empty and oversized input', async () => {
    await expect(parseSkillFile(file('content', 'report.pdf'))).rejects.toMatchObject({ code: 'format' });
    await expect(parseSkillFile(file(''))).rejects.toMatchObject({ code: 'size' });
    await expect(parseSkillFile(file(new Uint8Array(10 * 1024 * 1024 + 1)))).rejects.toMatchObject({ code: 'size' });
  });
});

describe('personal skill persistence', () => {
  let scope: string;
  let upload: globalThis.File;
  beforeEach(() => { scope = `tenant:user:${Math.random()}`; upload = file(markdown()); });

  async function save() {
    await changePersonalSkill(scope, { kind: 'save', manifest: await parseSkillFile(upload), file: upload });
    return (await listPersonalSkills(scope))[0];
  }

  it('persists bytes, enables by default and isolates account and tenant scope', async () => {
    const saved = await save();
    expect(saved.enabled).toBe(true);
    expect(await saved.file.text()).toBe(markdown());
    expect(await listPersonalSkills(`${scope}:different-tenant`)).toEqual([]);
    await expect(changePersonalSkill(`${scope}:different-user`, { kind: 'delete', target: saved })).rejects.toMatchObject({ code: 'conflict' });
    expect(await listPersonalSkills(scope)).toHaveLength(1);
  });
  it('rejects duplicate add and keeps the original bytes', async () => {
    const original = await save();
    await expect(save()).rejects.toMatchObject({ code: 'duplicate' });
    const rows = await listPersonalSkills(scope);
    expect(rows).toHaveLength(1);
    expect(rows[0].revision).toBe(original.revision);
    expect(await rows[0].file.text()).toBe(markdown());
  });
  it('updates in place, preserves disabled state and rejects stale changes', async () => {
    const original = await save();
    await changePersonalSkill(scope, { kind: 'toggle', target: original, enabled: false });
    await expect(changePersonalSkill(scope, { kind: 'delete', target: original })).rejects.toMatchObject({ code: 'conflict' });
    const current = (await listPersonalSkills(scope))[0];
    const replacement = file(markdown('updated-report'));
    await changePersonalSkill(scope, { kind: 'save', target: current, file: replacement, manifest: await parseSkillFile(replacement) });
    const updated = (await listPersonalSkills(scope))[0];
    expect(updated.id).toBe(original.id);
    expect(updated.name).toBe('updated-report');
    expect(updated.enabled).toBe(false);
    expect(await updated.file.text()).toBe(markdown('updated-report'));
    await changePersonalSkill(scope, { kind: 'delete', target: updated });
    expect(await listPersonalSkills(scope)).toEqual([]);
  });
});
