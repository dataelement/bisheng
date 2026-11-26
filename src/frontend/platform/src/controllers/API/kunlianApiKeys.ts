import axios from "@/controllers/request";
import type {
  KunlianApiKeyIssuePayload,
  KunlianApiKeyIssued,
  KunlianApiKeyItem,
  KunlianApiKeyUpdatePayload,
  KunlianIntegrationStatus,
  KunlianSyncTriggerResult,
  KunlianTenantsResponse,
} from "@/types/api/kunlianApiKey";

const KUNLIAN_API_KEYS_BASE = "/api/v1/identity-integrations/kunlian/api-keys";
const KUNLIAN_STATUS_PATH = "/api/v1/identity-integrations/kunlian/status";
const KUNLIAN_SYNC_PATH = "/api/v1/identity-integrations/kunlian/sync";
const KUNLIAN_TENANTS_PATH = "/api/v1/identity-integrations/kunlian/tenants";
const MAX_KEY_PAGE_SIZE = 100;
const MAX_FETCH_PAGES = 20;

export async function listKunlianApiKeysPageApi(params: {
  offset?: number;
  limit?: number;
} = {}): Promise<KunlianApiKeyItem[]> {
  return await axios.get(KUNLIAN_API_KEYS_BASE, { params });
}

/**
 * Load all Kunlian API keys across paginated slices so client-side status/keyword
 * filtering sees the full dataset. Stops as soon as a slice has fewer than 100 rows.
 */
export async function listAllKunlianApiKeysApi(): Promise<KunlianApiKeyItem[]> {
  const allItems: KunlianApiKeyItem[] = [];
  for (let pageIndex = 0; pageIndex < MAX_FETCH_PAGES; pageIndex += 1) {
    const offset = pageIndex * MAX_KEY_PAGE_SIZE;
    const batch = await listKunlianApiKeysPageApi({
      offset,
      limit: MAX_KEY_PAGE_SIZE,
    });
    const rows = Array.isArray(batch) ? batch : [];
    allItems.push(...rows);
    if (rows.length < MAX_KEY_PAGE_SIZE) {
      break;
    }
  }
  return allItems;
}

export async function getKunlianApiKeyDetailApi(
  keyId: number,
): Promise<KunlianApiKeyItem> {
  return await axios.get(`${KUNLIAN_API_KEYS_BASE}/${keyId}`);
}

export async function issueKunlianApiKeyApi(
  payload: KunlianApiKeyIssuePayload,
): Promise<KunlianApiKeyIssued> {
  return await axios.post(KUNLIAN_API_KEYS_BASE, payload);
}

export async function updateKunlianApiKeyApi(
  keyId: number,
  payload: KunlianApiKeyUpdatePayload,
): Promise<KunlianApiKeyItem> {
  return await axios.patch(`${KUNLIAN_API_KEYS_BASE}/${keyId}`, payload);
}

export async function rotateKunlianApiKeyApi(
  keyId: number,
): Promise<KunlianApiKeyIssued> {
  return await axios.post(`${KUNLIAN_API_KEYS_BASE}/${keyId}/rotate`);
}

export async function revokeKunlianApiKeyApi(
  keyId: number,
): Promise<KunlianApiKeyItem> {
  return await axios.post(`${KUNLIAN_API_KEYS_BASE}/${keyId}/revoke`);
}

/**
 * Fetch Kunlian integration status silently so environments without Kunlian sync
 * do not trigger global error notifications when opening the key creation dialog.
 */
export async function getKunlianIntegrationStatusSilentApi(): Promise<KunlianIntegrationStatus | null> {
  try {
    return await axios.get(KUNLIAN_STATUS_PATH, { silent: true });
  } catch {
    return null;
  }
}

export async function getKunlianIntegrationStatusApi(): Promise<KunlianIntegrationStatus> {
  return await axios.get(KUNLIAN_STATUS_PATH);
}

export async function triggerKunlianSyncApi(): Promise<KunlianSyncTriggerResult> {
  return await axios.post(KUNLIAN_SYNC_PATH);
}

/**
 * Fetch synced/bound Kunlian external tenants silently; environments without directory
 * state fall back cleanly to manual tenant ID entry.
 */
export async function getKunlianTenantsSilentApi(
  connectionId?: string,
): Promise<KunlianTenantsResponse | null> {
  try {
    return await axios.get(KUNLIAN_TENANTS_PATH, {
      params: connectionId ? { connection_id: connectionId } : undefined,
      silent: true,
    });
  } catch {
    return null;
  }
}
