from typing import List, Optional

from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao


class KnowledgeSpaceChatService:
    """ Service class for handling Knowledge Space AI Chat operations """

    @classmethod
    def generate_flow_id_for_file(cls, knowledge_id: int, file_id: int) -> str:
        """ Generate a unique flow_id representation for a single file chat """
        return f"space_{knowledge_id}_file_{file_id}"

    @classmethod
    def generate_flow_id_for_folder(cls, knowledge_id: int, folder_id: int) -> str:
        """ Generate a unique flow_id representation for a folder chat """
        return f"space_{knowledge_id}_folder_{folder_id}"

    @classmethod
    def chat_single_file(cls, knowledge_id: int, user_id: int, file_id: int, query: str) -> dict:
        """ Single file RAG query """
        # Verify file exists and is a file
        file_record = KnowledgeFileDao.query_by_id_sync(file_id)
        if not file_record or file_record.knowledge_id != knowledge_id or file_record.file_type != 1:
            raise ValueError("Invalid file for chat")

        flow_id = cls.generate_flow_id_for_file(knowledge_id, file_id)

        # design doc: generate a session record, support RAG
        # We assume there is a chat session manager in the wider system that takes flow_id and query
        # For now, we mock the core functionality.
        # TODO: integrate with actual RAG engine
        return {
            "flow_id": flow_id,
            "answer": f"Mock answer from single file {file_id}: {query}",
            "session_created": True
        }

    @classmethod
    def chat_folder(cls, knowledge_id: int, user_id: int, folder_id: int, query: str,
                    tags: Optional[List[int]] = None) -> dict:
        """ Folder RAG query """
        # Verify folder exists and is a folder
        if folder_id != 0:  # 0 means root folder perhaps, but usually handled nicely
            folder_record = KnowledgeFileDao.query_by_id_sync(folder_id)
            if not folder_record or folder_record.knowledge_id != knowledge_id or folder_record.file_type != 0:
                raise ValueError("Invalid folder for chat")

        flow_id = cls.generate_flow_id_for_folder(knowledge_id, folder_id)

        # tags filtering is supported

        # design doc: generate a session record, support RAG, support tags filtering
        # Assume actual RAG logic is delegated
        # TODO: integrate with actual RAG engine
        return {
            "flow_id": flow_id,
            "answer": f"Mock answer from folder {folder_id} with tags {tags}: {query}",
            "session_created": True
        }

    @classmethod
    def get_chat_sessions(cls, flow_id: str) -> List[dict]:
        """ Query sessions for a specific flow_id """
        # TODO: integrate with actual Session/Chat history DB model
        return [
            {"session_id": 1, "flow_id": flow_id, "title": "Mock Session 1"}
        ]
