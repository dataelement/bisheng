import axios from "@/controllers/request";
import type { KnowledgeSpaceInfo } from "./knowledgeSpace";

export interface SpaceSettingsUpdate {
  name: string;
  description: string;
  is_released: boolean;
  auth_type?: "public" | "private" | "approval";
  auto_tag_enabled?: boolean;
  auto_tag_library_id?: number | null;
  auto_tag_custom_tags?: string[] | null;
}
export function updateSpaceSettings(
  spaceId: number,
  body: SpaceSettingsUpdate,
): Promise<KnowledgeSpaceInfo> {
  return axios.put<unknown, KnowledgeSpaceInfo>(
    `/api/v1/knowledge/space/${spaceId}`,
    {
      name: body.name,
      description: body.description,
      is_released: body.is_released,
      ...(body.auth_type === undefined ? {} : { auth_type: body.auth_type }),
      ...(body.auto_tag_enabled === undefined
        ? {}
        : { auto_tag_enabled: body.auto_tag_enabled }),
      ...(body.auto_tag_library_id === undefined
        ? {}
        : { auto_tag_library_id: body.auto_tag_library_id }),
      ...(body.auto_tag_custom_tags === undefined
        ? {}
        : { auto_tag_custom_tags: body.auto_tag_custom_tags?.slice() ?? null }),
    },
  );
}
