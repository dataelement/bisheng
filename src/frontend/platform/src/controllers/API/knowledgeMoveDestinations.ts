import type {
  MoveDestinationItem,
  MoveDestinationServices,
  MoveFolder,
  MoveSpace,
} from "@bisheng/knowledge";
import request from "@/controllers/request";
import type {
  CursorPage,
  KnowledgeSpaceChild,
  KnowledgeSpaceSummary,
  KnowledgeSpaceInfo,
} from "./knowledgeSpace";

const spacePath = "/api/v1/knowledge/space";
const validId = (id: unknown): id is number =>
  typeof id === "number" && Number.isSafeInteger(id) && id > 0;

/** The host request wrapper owns authentication and management-scope enforcement. */
export function createMoveDestinationServices(
  tenantId: number,
): MoveDestinationServices {
  const headers = { "X-Management-Tenant": String(tenantId) };
  const listVisibleSpaces = async (
    signal: AbortSignal,
  ): Promise<KnowledgeSpaceInfo[]> => {
    const spaces = new Map<number, KnowledgeSpaceInfo>();
    const cursors = new Set<string>();
    let cursor: string | undefined;
    do {
      signal.throwIfAborted();
      const page = await request.get<unknown, CursorPage<KnowledgeSpaceInfo>>(
        `${spacePath}/list`,
        {
          headers,
          signal,
          params: { page_size: 200, cursor },
        },
      );
      for (const space of page.data)
        if (validId(space.id)) spaces.set(space.id, space);
      if (!page.has_more) break;
      if (!page.next_cursor || cursors.has(page.next_cursor))
        throw new Error("Move space cursor did not progress");
      cursor = page.next_cursor;
      cursors.add(cursor);
    } while (!signal.aborted);
    signal.throwIfAborted();
    return [...spaces.values()];
  };
  const listSpaces = async (signal: AbortSignal) => {
    const [visible, department, created, joined] = await Promise.all([
      listVisibleSpaces(signal),
      request.get<unknown, KnowledgeSpaceSummary[]>(`${spacePath}/department`, {
        headers,
        signal,
      }),
      request.get<unknown, KnowledgeSpaceSummary[]>(`${spacePath}/mine`, {
        headers,
        signal,
      }),
      request.get<unknown, KnowledgeSpaceSummary[]>(`${spacePath}/joined`, {
        headers,
        signal,
      }),
    ]);
    const visibleIds = new Set(visible.map((space) => space.id));
    const grouped = new Set<number>();
    const refine = (spaces: KnowledgeSpaceSummary[]): MoveSpace[] => {
      const result: MoveSpace[] = [];
      for (const space of spaces) {
        if (
          !validId(space.id) ||
          !visibleIds.has(space.id) ||
          grouped.has(space.id)
        )
          continue;
        grouped.add(space.id);
        result.push({ id: String(space.id), name: space.name });
      }
      return result;
    };
    // Visibility supplies navigation candidates; the immutable precheck owns upload authority.
    // Daily membership lists must not discard management-tenant or later-page candidates.
    const groups = {
      department: refine(department),
      created: refine(created),
      joined: refine(joined),
    };
    return {
      ...groups,
      available: visible
        .filter((space) => !grouped.has(space.id))
        .map((space) => ({ id: String(space.id), name: space.name })),
    };
  };
  const listDirectory = async (
    spaceId: string,
    parentId: string | null,
    signal: AbortSignal,
    foldersOnly: boolean,
  ): Promise<MoveDestinationItem[]> => {
    const rows = new Map<string, MoveDestinationItem>();
    const cursors = new Set<string>();
    let cursor: string | undefined;
    do {
      signal.throwIfAborted();
      const page = await request.get<unknown, CursorPage<KnowledgeSpaceChild>>(
        `${spacePath}/${spaceId}/children`,
        {
          headers,
          signal,
          params: {
            parent_id: parentId ?? undefined,
            file_type: foldersOnly ? 0 : undefined,
            page_size: 200,
            order_field: "file_name",
            order_sort: "asc",
            cursor,
          },
        },
      );
      for (const row of page.data) {
        if (!validId(row.id) || (foldersOnly && row.file_type !== 0)) continue;
        const type = row.file_type === 0 ? "folder" : "file";
        rows.set(`${type}:${row.id}`, {
          id: String(row.id),
          name: row.file_name,
          type,
        });
      }
      if (!page.has_more) break;
      if (!page.next_cursor || cursors.has(page.next_cursor))
        throw new Error("Move destination cursor did not progress");
      cursor = page.next_cursor;
      cursors.add(cursor);
    } while (!signal.aborted);
    signal.throwIfAborted();
    return [...rows.values()];
  };
  return {
    listSpaces,
    listFolders: async (spaceId, parentId, signal): Promise<MoveFolder[]> =>
      listDirectory(spaceId, parentId, signal, true),
    listChildren: (spaceId, parentId, signal) =>
      listDirectory(spaceId, parentId, signal, false),
  };
}
