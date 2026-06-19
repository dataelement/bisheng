/**
 * formatSeconds — render a millisecond duration as a whole-second "N 秒" label.
 * Shared by every elapsed-time indicator (daily /c DeepThinkingGroup + task-mode
 * DeepStepGroup) so the two surfaces format time identically and never drift.
 *
 * Whole seconds only. The backend stamps thinking / tool events at SECOND
 * granularity, so a frozen span is always an exact integer of seconds — a
 * trailing ".0" advertised a sub-second precision that does not exist and read as
 * a stuck decimal (only the integer ever moved). The live Date.now() tick is
 * rounded the same way so the running counter and the frozen value share one
 * format. Non-positive ⇒ "0" (callers hide the 用时 clause at <= 0, so a bare
 * "0 秒" never actually renders).
 */
export function formatSeconds(ms: number): string {
    const sec = !ms || ms <= 0 ? 0 : ms / 1000;
    return Math.round(sec).toString();
}
