import request from "./request";
import {
  mapSpace,
  type KnowledgeSpace,
  type RawKnowledgeSpace,
} from "./knowledge";

type Envelope<T> = { status_code: number; data: T };
type RawPage = {
  data: RawKnowledgeSpace[];
  page_size: number;
  has_more: boolean;
  next_cursor: string | null;
};
export type VisibleSpacesPage = Omit<RawPage, "data"> & {
  data: KnowledgeSpace[];
};

export async function getVisibleSpacesTenant(
  signal?: AbortSignal,
): Promise<number> {
  const response = await request.get<Envelope<{ leaf_tenant_id: number }>>(
    "/api/v1/user/current-tenant",
    { signal },
  );
  const tenant = response.data?.leaf_tenant_id;
  if (
    response.status_code !== 200 ||
    !Number.isSafeInteger(tenant) ||
    tenant <= 0
  ) {
    throw new Error("Invalid current tenant");
  }
  return tenant;
}

/** Visible candidates are permission filtered by the server, independently of membership. */
export async function getVisibleSpacesPageApi({
  cursor,
  keyword = "",
  page_size = 50,
  signal,
}: {
  cursor?: string;
  keyword?: string;
  page_size?: number;
  signal?: AbortSignal;
} = {}): Promise<VisibleSpacesPage> {
  if (!Number.isSafeInteger(page_size) || page_size < 1 || page_size > 200)
    throw new Error("Invalid page size");
  const response = await request.get<Envelope<RawPage>>(
    "/api/v1/knowledge/space/list",
    {
      params: { cursor, keyword: keyword.trim() || undefined, page_size },
      signal,
    },
  );
  const page = response.data;
  if (
    response.status_code !== 200 ||
    !page ||
    !Array.isArray(page.data) ||
    typeof page.has_more !== "boolean" ||
    (page.has_more &&
      (typeof page.next_cursor !== "string" ||
        !page.next_cursor ||
        page.next_cursor === cursor))
  ) {
    throw new Error("Invalid visible spaces page");
  }
  return {
    ...page,
    data: page.data
      .filter((row) => row.id != null && String(row.id) !== "")
      .map(mapSpace),
  };
}
