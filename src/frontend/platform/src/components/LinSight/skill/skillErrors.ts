// F035: map skill business error codes (110xx) to localized copy.
// skillApi mutation calls run in `silent` mode so the raw envelope reaches the
// caller and validation copy can go through i18n instead of backend English.

const SKILL_ERROR_KEYS: Record<number, string> = {
    11051: 'skillManage.errors.validation',
    11052: 'skillManage.errors.tooLarge',
    11053: 'skillManage.errors.notFound',
    11054: 'skillManage.errors.noPermission',
    11055: 'skillManage.errors.duplicate',
    11056: 'skillManage.errors.githubUrlInvalid',
    11057: 'skillManage.errors.githubFetch',
    11058: 'skillManage.errors.githubRateLimit',
    // 11052 = the uploaded payload is too big; 11059 = its unpacked contents are.
    // A well-compressing 7MB archive can trip 11059 alone, so they must not share copy.
    11059: 'skillManage.errors.bundleTooLarge',
};

export function getSkillErrorMessage(
    err: unknown,
    t: (key: string, options?: Record<string, unknown>) => string,
): string {
    if (err && typeof err === 'object' && 'status_code' in (err as any)) {
        const envelope = err as { status_code: number; status_message?: string };
        // 11051 covers a dozen distinct causes (missing frontmatter, bad description,
        // illegal name, ...) — the backend msg names the actual one, so surface it
        // instead of a canned catch-all that misleads (e.g. "archive must contain
        // SKILL.md" shown for an uppercase frontmatter name).
        if (envelope.status_code === 11051 && envelope.status_message) {
            return t('skillManage.errors.validationDetail', { detail: envelope.status_message });
        }
        const key = SKILL_ERROR_KEYS[envelope.status_code];
        if (key) return t(key);
        if (envelope.status_message) return envelope.status_message;
    }
    if (typeof err === 'string') return err;
    return t('skillManage.errors.unknown');
}
