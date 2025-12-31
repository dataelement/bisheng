from bisheng.telemetry.domain.mid_table.base import BaseMidTable, BaseRecord


class KnowledgeIncrementRecord(BaseRecord):
    knowledge_id: int
    knowledge_name: str
    knowledge_type: int


class KnowledgeIncrement(BaseMidTable):
    _index_name = 'mid_knowledge_increment'
    _mappings = {
        "knowledge_id": {"type": "integer"},
        "knowledge_name": {"type": "keyword", "fields": {"text": {"type": "text"}}},
        "knowledge_type": {"type": "integer"},
    }
