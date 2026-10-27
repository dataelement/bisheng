/** A recording replaces only its own text span and preserves surrounding edits. */
export class VoiceDraft {
  private previous: string;
  private start: number;
  private end: number;
  private frozen = false;

  constructor(value: string, position: number) {
    this.previous = value;
    this.start = this.end = Math.max(0, Math.min(value.length, position));
  }

  freeze(): void {
    this.frozen = true;
  }

  isFrozen(): boolean {
    return this.frozen;
  }

  reconcile(value: string): boolean {
    if (this.frozen) return false;
    if (value === this.previous) return true;
    let prefix = 0;
    while (
      prefix < value.length &&
      prefix < this.previous.length &&
      value[prefix] === this.previous[prefix]
    )
      prefix++;
    let suffix = 0;
    while (
      suffix < value.length - prefix &&
      suffix < this.previous.length - prefix &&
      value[value.length - 1 - suffix] ===
        this.previous[this.previous.length - 1 - suffix]
    )
      suffix++;
    const oldEnd = this.previous.length - suffix;
    if (oldEnd <= this.start) {
      const delta = value.length - this.previous.length;
      this.start += delta;
      this.end += delta;
    } else if (prefix < this.end) {
      this.frozen = true;
    }
    this.previous = value;
    return !this.frozen;
  }

  apply(current: string, transcript: string): string {
    if (!this.reconcile(current)) return current;
    const next =
      current.slice(0, this.start) + transcript + current.slice(this.end);
    this.end = this.start + transcript.length;
    this.previous = next;
    return next;
  }

  /** Index just after the dictated span, where the caret should stay. */
  caret(): number {
    return this.end;
  }
}
