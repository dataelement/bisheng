export function resolveUserAvatarUrl(value: string | null | undefined, baseUrl: string): string | undefined {
    const source = value?.trim();
    if (!source) return undefined;
    if (/^(https?:\/\/|\/\/)/i.test(source)) return source;
    if (/^[a-z][a-z\d+.-]*:/i.test(source)) return undefined;

    const prefix = baseUrl.replace(/\/+$/, '');
    const path = `/${source.replace(/^\/+/, '')}`;
    return prefix && !path.startsWith(`${prefix}/`) ? `${prefix}${path}` : path;
}
