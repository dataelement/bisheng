import request from "@/controllers/request";
import type { KnowledgeSpaceInfo } from "./knowledgeSpace";

export type SpaceSection = "department" | "created" | "joined";
export type SpaceSort = "update_time" | "create_time" | "name";

const sectionPath: Record<SpaceSection, string> = {
  department: "department",
  created: "mine",
  joined: "joined",
};

export function listNavigationSpaces(
  section: SpaceSection,
  orderBy: SpaceSort,
): Promise<KnowledgeSpaceInfo[]> {
  return request.get<unknown, KnowledgeSpaceInfo[]>(`/api/v1/knowledge/space/${sectionPath[section]}`, {
    params: { order_by: orderBy },
  });
}

export function setNavigationSpacePin(spaceId: number, pinned: boolean): Promise<boolean> {
  return request.post<unknown, boolean>(`/api/v1/knowledge/space/${spaceId}/set-pin`, {
    is_pined: pinned,
  });
}
