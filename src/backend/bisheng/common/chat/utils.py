import json
from enum import Enum
from urllib.parse import unquote, urlparse

from langchain_classic.schema.document import Document


class SourceType(Enum):
    """
    source type
    """

    NOT_SUPPORT = 0
    FILE = 1
    NO_PERMISSION = 2
    LINK = 3
    QA = 4


def sync_judge_source(result, source_document, chat_id, extra: dict):
    source = SourceType.NOT_SUPPORT.value
    if isinstance(result, Document):
        metadata = result.metadata
        question = result.page_content
        result = json.loads(metadata.get("extra", "{}")).get("answer")
        if result:
            source = SourceType.QA.value
            extra.update(
                {
                    "qa": question,
                    "url": json.loads(metadata.get("extra", "{}")).get("url"),
                }
            )
            return source, result
        source_document = [source_document]
    if source_document and chat_id:
        if any(not doc.metadata.get("right", True) for doc in source_document):
            source = SourceType.NO_PERMISSION.value
        elif all(
            doc.metadata.get("user_metadata") and doc.metadata.get("user_metadata", {}).get("url")
            for doc in source_document
        ):
            source = SourceType.LINK.value
            repeat_doc = {}
            doc = []
            for one in source_document:
                title = one.metadata.get("source") or one.metadata.get("document_name")
                url = one.metadata.get("user_metadata", {}).get("url")
                repeat_key = (title, url)
                if repeat_doc.get(repeat_key):
                    continue
                doc.append({"title": title, "url": url})
                repeat_doc[repeat_key] = 1
            extra.update({"doc": doc})
        else:
            source = SourceType.FILE.value
            for one in source_document:
                if not one.metadata.get("knowledge_id") or not one.metadata.get("document_id"):
                    source = SourceType.NOT_SUPPORT.value
                    break
                try:
                    int(one.metadata.get("knowledge_id"))
                    int(one.metadata.get("file_id") or one.metadata.get("document_id"))
                except Exception:
                    source = SourceType.NOT_SUPPORT.value
                    break

    return source, result


async def judge_source(result, source_document, chat_id, extra: dict):
    return sync_judge_source(result, source_document, chat_id, extra)


def process_node_data(node_data: list[dict]) -> dict:
    tweak = {}
    for nd in node_data:
        if nd.get("id") not in tweak:
            tweak[nd.get("id")] = {}
        if "InputFile" in nd.get("id", ""):
            file_path = nd.get("file_path")
            url_path = urlparse(file_path)
            if url_path.netloc:
                file_name = unquote(url_path.path.split("/")[-1])
            else:
                file_name = file_path.split("_", 1)[1] if "_" in file_path else ""
            nd["value"] = file_name
            tweak[nd.get("id")] = {"file_path": file_path, "value": file_name}
        elif "VariableNode" in nd.get("id", ""):
            variables = nd.get("name")
            variable_value = nd.get("value")
            variables_list = tweak[nd.get("id")].get("variables", [])
            if not variables_list:
                tweak[nd.get("id")]["variables"] = variables_list
                tweak[nd.get("id")]["variable_value"] = []
            variables_list.append(variables)
            variables_value_list = tweak[nd.get("id")].get("variable_value", [])
            variables_value_list.append(variable_value)
    return tweak
