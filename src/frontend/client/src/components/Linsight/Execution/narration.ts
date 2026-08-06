/**
 * One-line distillers: the step title fingerprint (firstLine) and the group
 * narration aside (extractNarration). Split out of stepUtils.ts.
 */
import type { MergedStep } from './execTypes';

/**
 * (A) Distil a one-line fingerprint from a step's output: first sentence / line,
 * newlines stripped, trimmed, truncated to ~24 chars with an ellipsis. Empty
 * input returns an empty string (caller falls back to a localized label).
 */
// Strip markdown NOISE markers shared by every one-line distiller (firstLine /
// extractNarration): fenced code blocks, inline code (kept as inner text), and
// emphasis / heading / quote / strike markers. Newlines are preserved (callers that
// treat a line as a thought boundary rely on them). Does NOT touch list bullets —
// firstLine wants to CUT at a list (keep the lead-in) while extractNarration wants to
// KEEP the item text (drop only the marker), so each handles bullets its own way.
function stripMarkdownMarkers(text: string): string {
    return text
        .replace(/```[\s\S]*?```/g, ' ') // fenced code blocks
        .replace(/`([^`]*)`/g, '$1') // inline code -> inner text
        .replace(/[*_#>~]/g, ' '); // emphasis / heading / quote / strike markers
}

const FIRST_LINE_MAX = 24;
// A structured-enumeration goal ("<lead-in>：1. … 2. …") — the lead-in instruction
// IS the gist; the numbered list is detail. Cut at the first list ordinal so the
// title reads "研究首尔美食探店攻略，请搜索并整理以下信息" instead of trailing a dangling
// "1.". A list ordinal = a short number + "." / ")" at a list position (preceded by
// a colon / comma / whitespace) whose marker is followed by whitespace/end — so a
// decimal ("3.5", marker not space-followed) or a mid-token ("601138.SH") never trips it.
const ENUM_ORDINAL = /[：:，,\s]\d{1,3}[.)](?=\s|$)/;
export function firstLine(text: string | null | undefined, max: number = FIRST_LINE_MAX): string {
    if (!text) return '';
    // strip markdown markers FIRST (so a goal/thinking that opens with `code`, **bold**,
    // ## heading … shows prose, not raw markup), then collapse whitespace and trim.
    let flat = stripMarkdownMarkers(text).replace(/\s+/g, ' ').trim();
    if (!flat) return '';
    // drop a single LEADING list marker the text opens with ("1. …", "- …", "• …") so a
    // goal that starts straight into a list shows the first item, not the bare marker.
    flat = flat.replace(/^(?:[-•‣◦]|\d{1,3}[.)])\s+/, '');
    // drop a TRAILING numbered enumeration, keeping the lead-in (only when there IS
    // lead-in text before the first ordinal — a goal that is purely a list falls
    // through to normal truncation).
    const enumStart = flat.search(ENUM_ORDINAL);
    if (enumStart > 0) {
        const lead = flat.slice(0, enumStart).replace(/[：:，,\s]+$/, '').trim();
        if (lead) flat = lead;
    }
    // prefer the first sentence boundary when it lands inside the budget, otherwise
    // hard-truncate. CJK 。！？… always terminate; ASCII ! ? terminate when followed by
    // whitespace/end; an ASCII "." does too BUT NOT when preceded by a digit — so a
    // ticker / decimal / list ordinal ("601138.SH", "3.5", "1.") is not a false boundary.
    const sentence = flat.match(/^.*?(?:[。！？…]|[!?](?=\s|$)|(?<!\d)\.(?=\s|$))/);
    const head = sentence && sentence[0].length <= max ? sentence[0] : flat;
    if (head.length <= max) return head;
    return head.slice(0, max) + '…';
}

const NARRATION_MIN_LEN = 4;
// A narration aside longer than this is almost certainly an instruction / list,
// not a natural "colleague reporting" line — skip it for a shorter sentence.
const NARRATION_MAX_LEN = 56;

// Unit boundaries WITHIN one line: CJK 。！？… always split; an ASCII !? only splits
// when followed by whitespace/end-of-string, and an ASCII "." additionally must NOT
// follow a digit — so a decimal / ticker / list ordinal ("76.5%", "601138.SH", "14.")
// is not a false sentence end. That last clause is why "13. 未来展望" + "14. 封底",
// welded into one line, no longer splits into the bare fragment "未来展望14." — it was
// the missing half of the boundary semantics firstLine has always used (this stays a
// separate const on purpose: firstLine matches a prefix, this splits into all units).
// Line breaks are handled by splitIntoUnits itself, which needs the line to tag list
// membership.
const UNIT_SPLIT = /(?<=[。！？…])|(?<=[!?](?=\s|$))|(?<=(?<!\d)\.(?=\s|$))/;

// A leading list marker ("- ", "* ", "1. ", "1)", "(1) "). Trailing whitespace is
// required so "-5%" / "3.5" are untouched.
const LIST_MARKER = /^[ \t]*(?:[-*•‣◦]|\d+[.)]|[（(]\d+[）)])[ \t]+/;

// A unit whose head is an ASCII lowercase letter / digit, or an English connective,
// reads as a split-off continuation or a data tail ("confirmed, and …", "6T, … etc.")
// rather than a fresh narration sentence. Demoted (not banned) — see the 3-pass scan.
const CONNECTIVE_HEAD = /^(and|but|or|so|because|which|that|then|also|however|moreover|etc)\b/i;
// Internal tool names leaking into reasoning ("让我调用 ask user。") are implementation
// noise, never a user-facing aside. Suppressed by default (decision 2026-06).
const INTERNAL_TOOL = /\b(ask_user|write_todos|search_knowledge_base|read_file|write_file|code_interpreter)\b/i;
const INTERNAL_TOOL_PHRASE = /(调用|call)\s*(ask[_ ]?user|write[_ ]?todos|search[_ ]?knowledge)/i;
// Internal virtual-filesystem plumbing ("notes are in scratch/.") — the agent's
// private scratchpad is never user-facing. Match the PATH form (slash) or an explicit
// "scratch dir/folder/pad" so the English idiom "from scratch" (no slash) is untouched.
// `output/` is intentionally NOT here — it is the deliverable location, user-facing.
const INTERNAL_PATH = /\bscratch\/|\bscratch(?:pad\b|\s+(?:dir|directory|folder|file|space|workspace)\b)/i;

/** Does the text contain any CJK ideograph? (used to skip lone non-CJK tails). */
function hasCJK(s: string): boolean {
    return /[一-鿿]/.test(s);
}

/** One thought unit plus where it came from. */
interface Unit {
    /** unit text, whitespace-collapsed, list marker removed */
    text: string;
    /** its source line opened with a list marker => the model was DRAFTING content */
    listItem: boolean;
}

/**
 * Split a cleaned thinking passage into trimmed thought units. ASCII terminators
 * only break at real sentence ends (UNIT_SPLIT), so decimals / tickers stay whole.
 *
 * Splitting per LINE first is what makes `listItem` knowable: the marker is stripped
 * (so the item text can still be judged as prose) but the fact that it was there is
 * kept. Every unit cut from a list line inherits the flag — an item like
 * "- PPT的用途是什么？（公司介绍、投资分析？）" splits into two units and the second one
 * would otherwise slip through with no trace of its origin.
 */
function splitIntoUnits(cleaned: string): Unit[] {
    const out: Unit[] = [];
    for (const line of cleaned.split('\n')) {
        const listItem = LIST_MARKER.test(line);
        for (const piece of line.replace(LIST_MARKER, '').split(UNIT_SPLIT)) {
            const text = piece.replace(/\s+/g, ' ').trim();
            if (text) out.push({ text, listItem });
        }
    }
    return out;
}

// A numbered outline / agenda label line the model drafts INTO its reasoning while
// composing a deliverable ("Day 7: 返程", "Day 1: 抵达福州…", "第3天：…", "Step 2: …") —
// content, not a narration aside. Shape: a short label CONTAINING A DIGIT, then a colon,
// then a value. The digit requirement keeps prose label-values ("结论：…", "Note: …") safe.
const OUTLINE_LABEL = /^[^。！？.!?,，、:：]{0,10}\d[^。！？.!?,，、:：]{0,3}[:：]\s*\S/;

// Two outline items welded together by a LOST line break: "13. 未来展望" + "14. 封底"
// arriving as one line leaves "未来展望14." — whose "14. " then reads as a sentence
// terminator and wins the cleanest pass. The backend no longer drops the newline
// (stream_event_mapper `_extract_thinking`), so this is the belt to that braces:
// a word glued straight onto an ordinal marker is never a sentence.
const FUSED_ORDINAL = /[一-鿿A-Za-z]\d{1,3}[.)]\s*$/;

// A heading-shaped fragment the model drafts INTO a deliverable ("结尾页 - 感谢聆听",
// "封面 — 公司名"): a short label, a dash, a value, and NO sentence terminator.
const TITLE_DASH = /^[^。！？.!?]{1,20}\s[-–—]\s\S/;

// First-person planning language — the "what am I about to do" voice that makes a good
// aside, as opposed to the noun phrases the model drafts as CONTENT.
//
// English only, on purpose: this is consulted at exactly one place, to waive the
// prefer-CJK demotion, and that branch is unreachable for a unit containing CJK. A
// Chinese word list here would be dead code.
//
// It is a waiver, never its own scan pass: a pass would override POSITION, and position
// is the stronger signal — given "Let me run it." early and "I just need to call the
// export tool." last, the last line is the right aside even though only the first
// matches the list.
const INTENT_EN = /\b(let me|let's|i (?:need|should|can|have|will|am|'ll|'m)|i'(?:ll|m|ve)|now i|next,? i|first,? i|then i|so i)\b/i;

/** Does this unit speak in the planning voice (vs. reading as drafted content)? */
function hasIntent(bare: string): boolean {
    return INTENT_EN.test(bare);
}

/**
 * Hard rejects applied in EVERY pass — the "this is drafted content, not an aside"
 * dimension the gates below have no way to see. The old rules were all structural
 * (length / parenthetical / colon-list / tool name), so a noun phrase and a verb
 * sentence scored identically and position alone decided; that is how outline
 * fragments kept winning.
 */
function isDraftedContent(u: Unit, term: boolean): boolean {
    if (u.listItem) return true; // came off a bulleted / numbered line
    if (/[?？]\s*$/.test(u.text)) return true; // a question the model posed to itself
    if (FUSED_ORDINAL.test(u.text)) return true; // "未来展望14."
    if (!term && TITLE_DASH.test(u.text)) return true; // "结尾页 - 感谢聆听"
    return false;
}

/**
 * Base prose gate — rejects what is STRUCTURALLY never a one-line aside, in EVERY
 * scan pass: out-of-window length, a bare parenthetical enumeration "(a, b, c)", a
 * colon-led 顿号/comma list "风险：a、b、c", a numbered outline label "Day 7: 返程", or a
 * leaked internal tool name / virtual-FS path. Language preference (CJK) is NOT here —
 * it is a strict-only demotion (see isStrictProse) so a meaningful English sentence can
 * still surface in Pass 3 when the CJK options are all junk. `bare` = unit sans trailing
 * terminators.
 */
function isBaseProse(bare: string): boolean {
    if (bare.length < NARRATION_MIN_LEN || bare.length > NARRATION_MAX_LEN) return false;
    const t = bare.trim();
    if (/^[(（[【]/.test(t) && /[)）\]】]$/.test(t)) return false; // bare parenthetical enumeration
    if (/[:：].*[、,].*[、,]/.test(bare)) return false; // colon + ≥2 separators = a list, not a sentence
    if (OUTLINE_LABEL.test(t)) return false; // numbered outline / agenda label line (drafted content)
    if (INTERNAL_TOOL.test(bare) || INTERNAL_TOOL_PHRASE.test(bare) || INTERNAL_PATH.test(bare)) {
        return false; // leaked internal tool name or virtual-FS scratchpad path
    }
    return true;
}

/**
 * Strict prose gate — base gate plus DEMOTIONS used by the first two passes: a lone
 * non-CJK tail in a Chinese passage (prefer CJK), and a continuation/data head
 * (lowercase / digit start, or a connective). So a clean CJK / capitalized sentence
 * wins over an English tail or a split-off fragment; Pass 3 drops these demotions so a
 * meaningful English sentence still surfaces when it is the only real sentence.
 */
function isStrictProse(bare: string, cjk: boolean): boolean {
    if (!isBaseProse(bare)) return false;
    // demote a lone English tail in a CJK passage — UNLESS it speaks in the planning
    // voice, which is what an aside is supposed to be. Without the waiver the demotion
    // stopped preferring Chinese PROSE and started preferring Chinese OUTLINE ITEMS,
    // since those are what a bilingual reasoning passage leaves as CJK candidates.
    if (cjk && !hasCJK(bare) && !hasIntent(bare)) return false;
    if (/^[a-z0-9]/.test(bare) || CONNECTIVE_HEAD.test(bare)) return false;
    return true;
}

/**
 * (Narration §3) Extract a one-line natural-language narration (旁白) from a
 * thinking passage. Pipeline:
 *  - Clean: drop fenced/inline code and markdown markers. List bullets survive to
 *    splitIntoUnits, which strips them per line while recording that they were there.
 *  - Split into UNITS on sentence terminators (CJK always; ASCII only at a real
 *    sentence end) AND newlines. Drop a trailing un-terminated fragment (mid-stream)
 *    so streaming never shows a half-typed line.
 *  - Pick the LAST unit that reads as a natural aside via a 3-pass scan:
 *      1. a terminator-ended STRICT-prose sentence (the cleanest case),
 *      2. any STRICT-prose unit (newline-bounded lines count — a completed line),
 *      3. a terminator-ended BASE-prose SENTENCE (relax the CJK/head demotions so a
 *         meaningful English sentence surfaces over CJK outline junk — but still a real
 *         sentence, not a newline-bounded heading fragment).
 *    Each pass walks from the last unit backward. Structural junk (parentheticals,
 *    lists, outline labels, leaked tool names, out-of-window lengths) and drafted
 *    content (list items, self-posed questions, fused ordinals, dashed headings) are
 *    rejected in every pass.
 *  - Nothing natural → '' (caller falls back to the activity-summary label; better
 *    blank than surfacing junk). The expanded thinking body is unaffected.
 *
 * NOTE the whole scan must hold up on every STREAMING PREFIX, not just the final
 * text: NarrationTicker keeps the last non-empty result on screen, so one bad line
 * that passes mid-stream stays pinned even after better text arrives.
 */
// A sentence terminator at the very end. Same asymmetry as UNIT_SPLIT: a "." right
// after a digit closes an ordinal or a decimal, not a sentence.
const ENDS_TERM = /(?:[。！？…!?]|(?<!\d)\.)\s*$/;

export function extractNarration(text: string | null | undefined): string {
    if (!text) return '';
    // List markers are NOT stripped here — splitIntoUnits strips them per line so it
    // can tag the unit as drafted content on the way past.
    const cleaned = stripMarkdownMarkers(text);
    // A trailing unit is INCOMPLETE only when the text ends mid-sentence (no
    // terminator and no trailing newline) — drop it.
    const endsClean = ENDS_TERM.test(cleaned) || /\n\s*$/.test(cleaned);
    const units = splitIntoUnits(cleaned);
    if (!units.length) return '';
    const complete = endsClean ? units : units.slice(0, -1);
    if (!complete.length) return '';

    const cjk = hasCJK(cleaned);
    const bareOf = (u: string) => u.replace(/[。！？.!?…]+$/, '').trim();
    const isTerm = (u: string) => ENDS_TERM.test(u);
    const scan = (accept: (bare: string, term: boolean) => boolean): string => {
        for (let i = complete.length - 1; i >= 0; i--) {
            const unit = complete[i];
            const term = isTerm(unit.text);
            if (isDraftedContent(unit, term)) continue;
            if (accept(bareOf(unit.text), term)) return unit.text;
        }
        return '';
    };

    return (
        // Pass 1: a terminator-ended, strict-prose sentence.
        scan((bare, term) => term && isStrictProse(bare, cjk)) ||
        // Pass 2: any strict-prose unit (newline-bounded lines have no terminator).
        scan((bare) => isStrictProse(bare, cjk)) ||
        // Pass 3: a terminator-ended base-prose sentence — relax the CJK/head demotions
        // so a meaningful English sentence beats the CJK outline junk it sits among,
        // while the terminator requirement keeps a heading fragment from surfacing.
        scan((bare, term) => term && isBaseProse(bare))
    );
}

/**
 * (Narration §3) Pick the narration for a group of steps. While `running`, use
 * the LATEST thinking passage's last sentence (live旁白); once done, use the LAST
 * thinking passage's last sentence (its final summarizing line). Returns '' when
 * the group has no thinking step (caller falls back to a localized label).
 */
export function narrationFromSteps(steps: MergedStep[] | null | undefined, running: boolean): string {
    const thinking = (steps || []).filter((s) => s && s.stepType === 'thinking');
    if (!thinking.length) return '';
    // running -> the most recent thinking passage; done -> the final one. Both
    // resolve to the last thinking step in document order for this render model.
    const target = thinking[thinking.length - 1];
    return extractNarration(target.output);
}
