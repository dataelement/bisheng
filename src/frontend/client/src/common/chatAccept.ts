import { MEDIA_SUFFIXES } from '~/pages/appChat/fileAcceptUtils';

const BASE_ACCEPT =
    '.pdf,.txt,.docx,.doc,.ppt,.pptx,.md,.html,.xls,.xlsx,.wps,.dps,.et';

const BASE_WITH_IMAGES =
    '.pdf,.txt,.docx,.doc,.ppt,.pptx,.md,.html,.xls,.xlsx,.doc,.png,.jpg,.jpeg,.bmp,.wps,.dps,.et';

const OFD_SUFFIX = '.ofd';

const MEDIA_ACCEPT = MEDIA_SUFFIXES.join(',').toLowerCase();

/**
 * Data / config / source files — TASK MODE ONLY.
 *
 * These have no document parser behind them and need none: task mode drops every
 * attachment into a workspace where the agent reads them with `read_file` and the
 * code interpreter opens them with pandas / json / sqlite. Gating them on "can the
 * ETL parse it" was the wrong question for that surface.
 *
 * Daily chat deliberately does NOT get these: it has no workspace and no code
 * interpreter, and its only way to use an attachment is to extract text into the
 * prompt — which throws `ChatFileParseError` and fails the whole turn for a type
 * the parser does not know.
 *
 * Keep in sync with the backend gate,
 * `linsight/domain/services/workbench_impl.py::_PASSTHROUGH_TEXT_EXTS`. This list
 * decides whether the user can pick the file; that set decides what happens to it.
 */
const TASK_MODE_DATA_ACCEPT =
    '.csv,.tsv,.json,.jsonl,.xml,.yaml,.yml,.toml,.ini,.conf,.log,.sql,.py,.js,.ts,.sh';

/**
 * Whether a file name matches an accept list by EXTENSION.
 *
 * Split out so the picker's gate and the "you just left task mode" cleanup share
 * one matcher — the cleanup only has a stored attachment's name to work with, not
 * a `File`, and a second hand-rolled matcher would drift from this one.
 */
export function isFileNameAccepted(fileName: string, accepts: string): boolean {
    if (!accepts || accepts === '*') return true;
    const lower = (fileName || '').toLowerCase();
    return accepts
        .split(',')
        .map((a) => a.trim().toLowerCase())
        .filter((a) => a.startsWith('.'))
        .some((ext) => lower.endsWith(ext));
}

export interface BuildChatAcceptOptions {
    enableMedia: boolean;
    enableEtl4lm: boolean;
    includeOfd: boolean;
    /** Task mode additionally accepts data/config/source files. */
    taskMode?: boolean;
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
    if (opts.taskMode) {
        base = `${base},${TASK_MODE_DATA_ACCEPT}`;
    }
    return base;
}
