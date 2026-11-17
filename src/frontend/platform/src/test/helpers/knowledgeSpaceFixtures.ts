import type { CursorPage, KnowledgeSpaceChild } from "@/controllers/API/knowledgeSpace";

export const row = (id = 11, name = "report.pdf", file_type = 1): KnowledgeSpaceChild => ({
  id,
  knowledge_id: 7,
  file_name: name,
  file_type,
  status: 2,
  parse_type: "uns",
  update_time: "2026-11-07T12:00:00",
});
export const page = (data: KnowledgeSpaceChild[], next_cursor: string | null = null): CursorPage<KnowledgeSpaceChild> => ({
  data,
  page_size: 40,
  has_more: next_cursor !== null,
  next_cursor,
});
