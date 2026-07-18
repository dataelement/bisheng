export function resolveConfigString(value: unknown, fallback = ''): string {
    return typeof value === 'string' ? value : fallback;
}
