import request from "@/controllers/request";
import type { KnowledgeSpaceInfo, PageData } from "./knowledgeSpace";

export interface SpaceCopyTask extends KnowledgeSpaceInfo {
  id: number;
  name: string;
  user_id: number;
  state: number;
  job_id: string;
  job_state: string;
  phase: "preparing" | "initializing" | "copying" | "failed";
  total_count: number;
  succeeded_count: number;
  failed_count: number;
}

/** Recoverable copies are task entries, not grants to unfinished space contents. */
export async function listOwnedSpaceCopies(): Promise<SpaceCopyTask[]> {
  const result: SpaceCopyTask[] = [];
  for (let page = 1; ; page += 1) {
    const response = await request.get<unknown, PageData<SpaceCopyTask>>("/api/v1/knowledge/space/copy/tasks", {
      params: { page, page_size: 100 },
    });
    result.push(...response.data);
    if (page * 100 >= response.total) return result;
  }
}
