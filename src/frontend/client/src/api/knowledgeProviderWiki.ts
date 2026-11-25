import { z } from 'zod';
import request from './request';

const positiveInteger = z.number().int().safe().positive();
const slug = z.string().min(1).max(255).refine(s =>
  !/[%?#\\\p{Cc}]/u.test(s) && s.split('/').every(segment => segment && segment !== '.' && segment !== '..'));
const node = z.object({ slug, title: z.string(), page_type: z.string().min(1) });
const summary = node.extend({ summary: z.string() });
const graph = z.object({ nodes: z.array(node), edges: z.array(z.object({ source: slug, target: slug })) });
// Only an unambiguous local file id may become a link. Never carry provider fields into the view.
const source = z.unknown().transform(value => {
  const local = z.object({ file_id: positiveInteger }).strict().safeParse(value);
  return local.success ? local.data.file_id : null;
});
const page = summary.extend({ content: z.string(), in_links: z.array(slug), out_links: z.array(slug), sources: z.array(source) });
const status = z.discriminatedUnion('state', [
  z.object({ state: z.literal('preparing'), generation: positiveInteger.nullable() }),
  z.object({ state: z.enum(['generating', 'updating', 'empty', 'ready', 'query_failed']), generation: positiveInteger }),
]);
export type WikiGraph = z.infer<typeof graph>;
export type WikiPage = z.infer<typeof page>;
export type WikiScope = { spaceId: string; tenant: string; generation: number };
type Endpoint = 'status' | 'graph' | 'search' | 'page';
async function read<T>(spaceId: string, tenant: string, endpoint: Endpoint, schema: z.ZodType<T, z.ZodTypeDef, unknown>, signal?: AbortSignal, params?: Record<string, string | number>) {
  const response = await request.getResponse<{ headers: Record<string, string>; data: unknown }>(
    `/api/v1/knowledge/space/${encodeURIComponent(spaceId)}/wiki/${endpoint}`, { params, signal, showError: false, skip403Redirect: true },
  );
  const confirmed = response.headers['x-management-tenant'];
  if (!/^[1-9]\d*$/.test(confirmed) || confirmed !== tenant) throw new Error('Unconfirmed Wiki scope');
  const envelope = z.object({ status_code: z.literal(200), data: z.unknown() }).parse(response.data);
  return { tenant: confirmed, data: schema.parse(envelope.data) };
}
export async function readWikiStatus(spaceId: string, tenant: string, signal?: AbortSignal) {
  const result = await read(spaceId, tenant, 'status', status, signal);
  return { ...result.data, tenant: result.tenant };
}
export async function readWikiGraph({ spaceId, generation, tenant }: WikiScope, signal?: AbortSignal) {
  return (await read(spaceId, tenant, 'graph', graph, signal, { generation })).data;
}
export async function searchWiki({ spaceId, generation, tenant }: WikiScope, q: string, signal?: AbortSignal) {
  return (await read(spaceId, tenant, 'search', z.array(summary), signal, { generation, q })).data;
}
export async function readWikiPage({ spaceId, generation, tenant }: WikiScope, selectedSlug: string, signal?: AbortSignal) {
  const result = await read(spaceId, tenant, 'page', page, signal, { generation, slug: selectedSlug });
  if (result.data.slug !== selectedSlug) throw new Error('Wiki page changed');
  return result.data;
}
