/**
 * Demo data layer — DEV ONLY, opt-in. Pads the workbench module lists (知识空间 / 频道 /
 * 应用 / 技能广场) with sample rows so layouts can be reviewed on a backend that has little
 * data. Real rows always come first; sample rows are appended to the same response, in
 * the backend's own row shape, so every mapper and component downstream runs unchanged.
 *
 * Enable with `VITE_DEMO_DATA=true` (src/frontend/.env.development.local), or per browser
 * with `localStorage.setItem('bs_demo_data', '1')`. `request.ts` loads this module behind
 * `import.meta.env.DEV`, so it is never part of a production bundle.
 *
 * Sample rows exist only in these list responses — the backend has never heard of them.
 * Their ids carry DEMO_ID_PREFIX; anything that would open one must check isDemoId first.
 * The copy lives in the sibling JSON files so this source stays free of UI strings.
 */
import { DEMO_ID_PREFIX, isDemoDataEnabled } from './ids';
import apps from './apps.json';
import channels from './channels.json';
import knowledgeSpaces from './knowledgeSpaces.json';
import skills from './skills.json';

export { DEMO_ID_PREFIX, isDemoDataEnabled, isDemoId } from './ids';

// Structural slices of the axios types this file touches: raw axios imports are reserved
// for ~/api/request (constitution C7), and that wrapper is what hands the instance over.
type DemoResponse = {
  data: unknown;
  config: { url?: string; method?: string; params?: unknown };
};
type DemoAxiosInstance = {
  interceptors: { response: { use: (onFulfilled: <T extends DemoResponse>(response: T) => T) => unknown } };
};

type Envelope = { data?: unknown };
type Row = { id?: unknown };

/** Append rows the response does not already hold (a refetch must not duplicate them). */
function appendRows(existing: unknown, extra: Row[]): unknown[] {
  const rows = Array.isArray(existing) ? existing : [];
  const seen = new Set(rows.map((row) => String((row as Row)?.id)));
  return [...rows, ...extra.filter((row) => !seen.has(String(row.id)))];
}

function padList(response: DemoResponse, extra: Row[]) {
  const body = response.data as Envelope | unknown[];
  if (Array.isArray(body)) response.data = appendRows(body, extra);
  else if (body && typeof body === 'object') body.data = appendRows(body.data, extra);
}

const SPACE_LISTS: Record<string, Row[]> = {
  '/api/v1/knowledge/space/department': knowledgeSpaces.department,
  '/api/v1/knowledge/space/mine': knowledgeSpaces.mine,
  '/api/v1/knowledge/space/joined': knowledgeSpaces.joined,
};

function patch(response: DemoResponse) {
  const { url = '', method = 'get', params } = response.config;
  if (method.toLowerCase() !== 'get') return;
  const path = url.split('?')[0];

  if (SPACE_LISTS[path]) {
    padList(response, SPACE_LISTS[path]);
    return;
  }

  if (path === '/api/v1/channel/manager/my_channels') {
    const queryType = (params as { query_type?: string } | undefined)?.query_type;
    padList(response, queryType === 'followed' ? channels.followed : channels.created);
    return;
  }

  if (path === '/api/v1/linsight/skill/selectable') {
    // Enterprise skills (技能广场 + the chat input's skill menu). Rows are keyed by
    // `name`, which carries the demo prefix; the personal side has no endpoint — see
    // ./skills.ts.
    padList(response, skills.platform.map((skill) => ({ ...skill, id: skill.name })));
    return;
  }

  if (path === '/api/v1/workstation/app/used') {
    // Paged: sample apps ride on the first page only, and `total` grows with them so
    // the page's "has more" arithmetic still adds up.
    if (Number((params as { page?: number } | undefined)?.page ?? 1) !== 1) return;
    const payload = (response.data as Envelope)?.data as { list?: unknown[]; total?: number } | undefined;
    if (!payload) return;
    const before = Array.isArray(payload.list) ? payload.list.length : 0;
    payload.list = appendRows(payload.list, apps);
    payload.total = Number(payload.total ?? 0) + (payload.list.length - before);
  }
}

export function installDemoData(instance: DemoAxiosInstance) {
  if (!isDemoDataEnabled()) return;
  // Registered from a dynamic import, i.e. after request.ts's own interceptors — and
  // response interceptors run in registration order, so this sees the raw success
  // response the app code is about to receive.
  instance.interceptors.response.use((response) => {
    try {
      patch(response);
    } catch (error) {
      console.warn(`[demo-data] failed to pad ${response.config.url}`, error);
    }
    return response;
  });
  // warn, not info: it should be hard to miss that some of what is on screen is fake.
  console.warn(`[demo-data] sample rows enabled (ids prefixed "${DEMO_ID_PREFIX}")`);
}
