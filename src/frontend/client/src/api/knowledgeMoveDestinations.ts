import type { MoveDestinationItem, MoveDestinationServices, MoveSpace } from '@bisheng/knowledge';
import request from './request';

interface SpaceRow {
  id: number;
  name: string;
}

interface DirectoryPage {
  data: { id: number; file_name: string; file_type: number }[];
  has_more: boolean;
  next_cursor: string | null;
}

const spacePath = '/api/v1/knowledge/space';
const validId = (id: number) => Number.isSafeInteger(id) && id > 0;

export const moveDestinationServices: MoveDestinationServices = {
  async listSpaces(signal) {
    const [uploadable, department, created, joined] = await Promise.all([
      request.get<{ data: { data: SpaceRow[] } }>(`${spacePath}/uploadable`, { signal }),
      request.get<{ data: SpaceRow[] }>(`${spacePath}/department`, { signal }),
      request.get<{ data: SpaceRow[] }>(`${spacePath}/mine`, { signal }),
      request.get<{ data: SpaceRow[] }>(`${spacePath}/joined`, { signal }),
    ]);
    const allowed = new Set(uploadable.data.data.filter((space) => validId(space.id)).map((space) => space.id));
    const refine = (spaces: SpaceRow[]): MoveSpace[] => [...new Map(spaces
      .filter((space) => validId(space.id) && allowed.has(space.id))
      .map((space) => [space.id, { id: String(space.id), name: space.name }])).values()];
    return { department: refine(department.data), created: refine(created.data), joined: refine(joined.data) };
  },
  listFolders: (spaceId, parentId, signal) => listDirectory(spaceId, parentId, signal, true),
  listChildren: (spaceId, parentId, signal) => listDirectory(spaceId, parentId, signal, false),
};

async function listDirectory(spaceId: string, parentId: string | null, signal: AbortSignal, foldersOnly: boolean): Promise<MoveDestinationItem[]> {
  const rows = new Map<string, MoveDestinationItem>();
  const cursors = new Set<string>();
  let cursor: string | undefined;
  do {
    signal.throwIfAborted();
    const response = await request.get<{ data: DirectoryPage }>(`${spacePath}/${spaceId}/children`, {
      signal,
      params: {
        parent_id: parentId ?? undefined,
        file_type: foldersOnly ? 0 : undefined,
        page_size: 200,
        order_field: 'file_name',
        order_sort: 'asc',
        cursor,
      },
    });
    const page = response.data;
    for (const row of page.data) {
      if (!validId(row.id) || (foldersOnly && row.file_type !== 0)) continue;
      const type = row.file_type === 0 ? 'folder' : 'file';
      rows.set(`${type}:${row.id}`, { id: String(row.id), name: row.file_name, type });
    }
    if (!page.has_more) break;
    if (!page.next_cursor || cursors.has(page.next_cursor)) throw new Error('Move destination cursor did not progress');
    cursor = page.next_cursor;
    cursors.add(cursor);
  } while (!signal.aborted);
  signal.throwIfAborted();
  return [...rows.values()];
}
