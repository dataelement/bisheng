/** @jest-environment node */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';

/**
 * Where the mounted-knowledge-space row sits is a design decision, and it has
 * been lost once already.
 *
 * Figma 12841:47449 puts it in a gray strip ABOVE the input box, overlapping it
 * by the box's 16px corner radius so the white box appears to emerge from the
 * strip. A commit titled "调整工作台上传视频文件逻辑" rewrote this area while
 * changing upload handling and folded the row inside the box instead — the
 * layout was collateral, not a decision, and nothing in the diff said so.
 *
 * Attachments are deliberately NOT in the strip: files stay inline inside the
 * box, where they read as part of what you are about to send. Task-mode skills
 * are the opposite — they are mounted context like a knowledge space, so they
 * belong in the strip and not in the file row.
 */

function source(relative: string): string {
    return readFileSync(join(process.cwd(), relative), 'utf8');
}

describe('the attachment row keeps its designed placement', () => {
    const bar = source('src/components/Chat/Input/AttachmentBar.tsx');
    const input = source('src/components/Chat/AiChatInput.tsx');

    it('offers a strip appearance with the overlap that makes the shape continuous', () => {
        expect(bar).toContain('appearance');
        // The overlap IS the effect; without it the two read as stacked cards.
        expect(bar).toContain('-mb-4');
        expect(bar).toContain('rounded-t-2xl');
        expect(bar).toContain('bg-[rgba(244,244,244,0.55)]');
    });

    it('mounts knowledge spaces and task-mode skills in the strip, above the box', () => {
        expect(input).toContain('appearance="strip"');
        expect(input).toContain('hasMountedKbs');
        expect(input).toContain('skills={mountedSkills}');
        // Removing a skill has to stay reachable from the strip card.
        expect(input).toMatch(/appearance="strip"[\s\S]*?onRemoveSkill/);
    });

    it('keeps attachments inline inside the box, without knowledge spaces or skills', () => {
        expect(input).toContain('hasInlineAttachments');
        // The inline row carries files only.
        expect(input).toContain('kbs={[]}');
        expect(input).toContain('skills={[]}');
        // The file row must not be what makes a skill visible.
        expect(input).not.toContain('skills={taskMode ? dailySkills : []}');
    });

    it('shows the strip for a skill picked before any knowledge space', () => {
        // Without this, entering task mode and picking a skill on a fresh
        // conversation would render nothing until a space is also mounted.
        expect(input).toMatch(/const hasMountedKbs =[\s\S]*?mountedSkills\.length > 0/);
    });

    it('keeps the box painted above the strip it overlaps', () => {
        expect(input).toContain('relative z-[1]');
    });
});
