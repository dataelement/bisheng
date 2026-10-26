from bisheng.common.errcode.knowledge_space import McpFolderRetrievalScopeLimitError
from bisheng.knowledge.domain.services.knowledge_mcp_query_service import KnowledgeMcpQueryService

MAX_FOLDER_RETRIEVAL_FILES = 1000
FOLDER_RETRIEVAL_BATCH_SIZE = 100


class KnowledgeMcpFolderRetrievalService:
    def __init__(self, query: KnowledgeMcpQueryService) -> None:
        self.query = query

    async def resolve_file_ids(self, *, knowledge_id: int, folder_id: int, recursive: bool) -> list[int]:
        await self.query.require_space(knowledge_id)
        path = await self.query.folder_path(knowledge_id, folder_id)
        after = None
        seen: set[int] = set()
        file_ids: list[int] = []
        while True:
            rows = await self.query.repository.scan_files(
                [knowledge_id],
                file_type=1,
                parent_path=path,
                recursive=recursive,
                statuses=[2],
                after=after,
                sort_by="file_name",
                order="asc",
                limit=FOLDER_RETRIEVAL_BATCH_SIZE,
            )
            if not rows:
                return file_ids
            next_key = self.query.file_key(rows[-1], "file_name")
            if next_key == after or any(int(row.id) in seen for row in rows):
                raise ValueError("folder inventory pagination did not advance")
            seen.update(int(row.id) for row in rows)
            if len(seen) > MAX_FOLDER_RETRIEVAL_FILES:
                raise McpFolderRetrievalScopeLimitError()
            for row in rows:
                if await self.query.visible(row):
                    file_ids.append(int(row.id))
            if len(rows) < FOLDER_RETRIEVAL_BATCH_SIZE:
                return file_ids
            after = next_key
