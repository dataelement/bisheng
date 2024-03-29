def set_flow_knowledge_id(graph_data: dict, knowledge_id: int):

    for node in graph_data['nodes']:
        if 'VectorStore' in node['data']['node']['base_classes']:
            if 'collection_name' in node['data'].get('node').get('template').keys():
                node['data']['node']['template']['collection_name']['collection_id'] = knowledge_id
            if 'index_name' in node['data'].get('node').get('template').keys():
                node['data']['node']['template']['index_name']['collection_id'] = knowledge_id
    return graph_data
