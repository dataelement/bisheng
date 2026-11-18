import type { Mock } from "vitest";
import type { ProcessingJobRead } from "@/controllers/API/knowledgeSpace";

export const taskKinds = ["embedding_rebuild", "move_index"] as const;
export const jobsPath = "/api/v1/knowledge/space/7/processing-jobs";
type TaskKind = (typeof taskKinds)[number];

export function mockTaskRecords(get: Mock, kinds: readonly TaskKind[]) {
  const jobs: ProcessingJobRead[] = kinds.map((kind) => ({
    id: `job-${kind}`,
    space_id: 7,
    kind,
    state: "succeeded",
    revision: 1,
    accepted_at: "2026-11-17T09:00:00",
    started_at: null,
    finished_at: null,
    total_count: 1,
    succeeded_count: 1,
    failed_count: 0,
    pending_count: 0,
    hidden_item_count: 0,
    retryable: false,
    error_code: null,
    obsolete_reason: null,
  }));
  const read = get.getMockImplementation()!;
  get.mockImplementation(async (url: string, options?: { params?: { kind?: string } }) => {
    if (url === jobsPath) {
      const data = jobs.filter(({ kind }) => kind === options?.params?.kind);
      return { data, total: data.length };
    }
    if (url.startsWith(`${jobsPath}/`) && url.endsWith("/items")) return { data: [], total: 0 };
    const job = jobs.find(({ id }) => url === `${jobsPath}/${id}`);
    return job ?? read(url, options);
  });
}
