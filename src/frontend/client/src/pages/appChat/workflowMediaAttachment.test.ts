/** @jest-environment node */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';

/**
 * Regression guard: a workflow attachment must keep its media metadata.
 *
 * A video sent from a workflow rendered as a bare "MP4" card while the same
 * file in daily chat showed its poster frame. The backend stores the
 * attachment as it receives it, so the loss was entirely on this side — the
 * object gets narrowed twice, and both narrowings dropped the cover:
 *
 *   - useWebsocket maps each picked file down to id/name/url before sending
 *   - useChatHelpers maps each stored row down again when history loads
 *
 * Either one silently un-fixes the feature, which is why this is a source
 * assertion rather than a behavioural one: the failure mode is somebody
 * rewriting one of the two literals without knowing about the other.
 */

function source(file: string): string {
    return readFileSync(join(process.cwd(), 'src/pages/appChat', file), 'utf8');
}

describe('workflow media attachments keep what the chip draws', () => {
    it('the send payload carries the poster and the length', () => {
        const websocket = source('useWebsocket.ts');
        expect(websocket).toContain('const messageFiles =');
        expect(websocket).toContain('cover_filepath: f.cover_filepath');
        expect(websocket).toContain('mediaDurationSec: f.mediaDurationSec');
    });

    it('the history row carries them back', () => {
        const helpers = source('useChatHelpers.ts');
        expect(helpers).toContain('cover_filepath: el.cover_filepath');
        expect(helpers).toContain('mediaDurationSec: el.mediaDurationSec');
    });

    it('the chip still reads the field both of them carry', () => {
        const chip = readFileSync(
            join(process.cwd(), 'src/pages/appChat/components/AppChatFileChip.tsx'),
            'utf8',
        );
        expect(chip).toContain('cover_filepath: file.cover_filepath');
    });
});
