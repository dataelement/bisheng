export function normalizeSearchMapping(mapping: Record<string, string> = {}): Record<string, string> {
    return {
        results: mapping.results ?? '',
        title: mapping.title ?? '',
        url: mapping.url ?? '',
        snippet: mapping.snippet ?? '',
        source: mapping.source ?? '',
        siteIcon: mapping.siteIcon ?? '',
        datePublished: mapping.datePublished ?? '',
    };
}
