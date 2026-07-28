import { MEDIA_SUFFIXES } from '~/pages/appChat/fileAcceptUtils';

const BASE_ACCEPT =
    '.pdf,.txt,.docx,.doc,.ppt,.pptx,.md,.html,.xls,.xlsx,.wps,.dps,.et';

const BASE_WITH_IMAGES =
    '.pdf,.txt,.docx,.doc,.ppt,.pptx,.md,.html,.xls,.xlsx,.doc,.png,.jpg,.jpeg,.bmp,.wps,.dps,.et';

const OFD_SUFFIX = '.ofd';

const MEDIA_ACCEPT = MEDIA_SUFFIXES.join(',').toLowerCase();

export interface BuildChatAcceptOptions {
    enableMedia: boolean;
    enableEtl4lm: boolean;
    includeOfd: boolean;
}

/** Runtime accept string for workbench chat file picker (replaces const enum). */
export function buildChatAccept(opts: BuildChatAcceptOptions): string {
    let base = opts.enableEtl4lm ? BASE_WITH_IMAGES : BASE_ACCEPT;
    if (opts.includeOfd) {
        base = `${base},${OFD_SUFFIX}`;
    }
    if (opts.enableMedia) {
        base = `${base},${MEDIA_ACCEPT}`;
    }
    return base;
}
