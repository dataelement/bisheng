from bisheng.template.field.base import TemplateField
from bisheng.template.template.base import Template
from langchain.pydantic_v1 import BaseModel
from langchain_core.language_models import BaseLanguageModel


def set_flow_knowledge_id(graph_data: dict, knowledge_id: int):

    for node in graph_data['nodes']:
        if 'VectorStore' in node['data']['node']['base_classes']:
            if 'collection_name' in node['data'].get('node').get('template').keys():
                node['data']['node']['template']['collection_name']['collection_id'] = knowledge_id
            if 'index_name' in node['data'].get('node').get('template').keys():
                node['data']['node']['template']['index_name']['collection_id'] = knowledge_id
    return graph_data


def replace_flow_llm(graph_data: dict, llm: BaseLanguageModel, llm_param: dict):
    # 替换class, 替换template， 其他不动，
    for node in graph_data['nodes']:
        if 'BaseLanguageModel' in node['data']['node']['base_classes']:
            node['data']['type'] = type(llm).__name__
            node['data']['node']['template'] = trans_obj_to_json(llm, llm_param)

    return graph_data


def trans_obj_to_json(obj: BaseModel, llm_param: dict):
    # template 构建
    template = []
    field_json = obj.__dict__
    for k, v in field_json.items():
        if k in llm_param:
            template.append(
                TemplateField(field_type=type(v).__name__, name=k,
                              value=llm_param.get(k)).to_dict())
    return Template(type_name=type(obj).__name__, fields=template).to_dict()
