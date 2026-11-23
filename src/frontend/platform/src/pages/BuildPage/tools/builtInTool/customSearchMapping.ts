import type { SearchProof } from '@/controllers/API/webSearch';

type Parameter = { location: string; name: string };
export type LegacyDraft = {
    operation: { server: string; method: string; path: string; query_parameter: Parameter; fixed_params: { location: string; name: string; value: string | number | boolean }[]; auth: { location: string; name: string } };
    mapping: Record<string, string>;
    proof?: SearchProof;
};
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
