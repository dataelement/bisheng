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
 * box, where they read as part of what you are about to send.
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

    it('mounts knowledge spaces in the strip, above the box', () => {
        expect(input).toContain('appearance="strip"');
        expect(input).toContain('hasMountedKbs');
    });

    it('keeps attachments inline inside the box', () => {
        expect(input).toContain('hasInlineAttachments');
        // The inline row carries files and skills, never knowledge spaces.
        expect(input).toContain('kbs={[]}');
    });

    it('keeps the box painted above the strip it overlaps', () => {
        expect(input).toContain('relative z-[1]');
    });
});
