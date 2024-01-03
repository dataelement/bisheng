from bisheng.api.v1.schemas import StreamData
from bisheng.database.base import get_session, session_getter
from bisheng.database.models.role_access import AccessType, RoleAccess
from bisheng.database.models.variable_value import Variable
from bisheng.graph.graph.base import Graph
from bisheng.utils.logger import logger
from sqlalchemy import delete
from sqlmodel import select

API_WORDS = ['api', 'key', 'token']


def has_api_terms(word: str):
    return 'api' in word and ('key' in word or ('token' in word and 'tokens' not in word))


def remove_api_keys(flow: dict):
    """Remove api keys from flow data."""
    if flow.get('data') and flow['data'].get('nodes'):
        for node in flow['data']['nodes']:
            node_data = node.get('data').get('node')
            template = node_data.get('template')
            for value in template.values():
                if (isinstance(value, dict) and has_api_terms(value['name'])
                        and value.get('password')):
                    value['value'] = None

    return flow


def build_input_keys_response(langchain_object, artifacts):
    """Build the input keys response."""

    input_keys_response = {
        'input_keys': {
            key: ''
            for key in langchain_object.input_keys
        },
        'memory_keys': [],
        'handle_keys': artifacts.get('handle_keys', []),
    }

    # Set the input keys values from artifacts
    for key, value in artifacts.items():
        if key in input_keys_response['input_keys']:
            input_keys_response['input_keys'][key] = value
    # If the object has memory, that memory will have a memory_variables attribute
    # memory variables should be removed from the input keys
    if hasattr(langchain_object, 'memory') and hasattr(langchain_object.memory,
                                                       'memory_variables'):
        # Remove memory variables from input keys
        input_keys_response['input_keys'] = {
            key: value
            for key, value in input_keys_response['input_keys'].items()
            if key not in langchain_object.memory.memory_variables
        }
        # Add memory variables to memory_keys
        input_keys_response['memory_keys'] = langchain_object.memory.memory_variables

    if hasattr(langchain_object, 'prompt') and hasattr(langchain_object.prompt, 'template'):
        input_keys_response['template'] = langchain_object.prompt.template

    return input_keys_response


def build_flow(graph_data: dict,
               artifacts,
               process_file=False,
               flow_id=None,
               chat_id=None,
               **kwargs) -> Graph:
    try:
        # Some error could happen when building the graph
        graph = Graph.from_payload(graph_data)
    except Exception as exc:
        logger.error(exc)
        error_message = str(exc)
        yield str(StreamData(event='error', data={'error': error_message}))
        return

    number_of_nodes = len(graph.nodes)

    for i, vertex in enumerate(graph.generator_build(), 1):
        try:
            log_dict = {
                'log': f'Building node {vertex.vertex_type}',
            }
            yield str(StreamData(event='log', data=log_dict))
            # # 如果存在文件，当前不操作文件，避免重复操作
            if not process_file and vertex.base_type == 'documentloaders':
                template_dict = {
                    key: value
                    for key, value in vertex.data['node']['template'].items()
                    if isinstance(value, dict)
                }
                for key, value in template_dict.items():
                    if value.get('type') == 'fileNode':
                        # 过滤掉文件
                        vertex.params[key] = ''

            # vectore store 引入自动建库逻辑
            # 聊天窗口等flow 主动生成的vector 需要新建临时collection
            # tmp_{chat_id}
            if vertex.base_type == 'vectorstores':
                # 知识库通过参数传参
                if 'collection_name' in kwargs and 'collection_name' in vertex.params:
                    vertex.params['collection_name'] = kwargs['collection_name']
                if 'collection_name' in kwargs and 'index_name' in vertex.params:
                    vertex.params['index_name'] = kwargs['collection_name']

                if 'collection_name' in vertex.params and not vertex.params.get('collection_name'):
                    vertex.params['collection_name'] = f'tmp_{flow_id}_{chat_id if chat_id else 1}'
                elif 'index_name' in vertex.params and not vertex.params.get('index_name'):
                    # es
                    vertex.params['index_name'] = f'tmp_{flow_id}_{chat_id if chat_id else 1}'

            vertex.build()
            params = vertex._built_object_repr()
            valid = True
            logger.debug(
                f"Building node {str(params)[:50]}{'...' if len(str(params)) > 50 else ''}")
            if vertex.artifacts:
                # The artifacts will be prompt variables
                # passed to build_input_keys_response
                # to set the input_keys values
                artifacts.update(vertex.artifacts)
        except Exception as exc:
            params = str(exc)
            valid = False
            response = {
                'valid': valid,
                'params': params,
                'id': vertex.id,
                'progress': round(i / number_of_nodes, 2),
            }
            yield str(StreamData(event='message', data=response))
            raise exc

        response = {
            'valid': valid,
            'params': params,
            'id': vertex.id,
            'progress': round(i / number_of_nodes, 2),
        }
        yield str(StreamData(event='message', data=response))
    return graph


def build_flow_no_yield(graph_data: dict,
                        artifacts,
                        process_file=False,
                        flow_id=None,
                        chat_id=None,
                        **kwargs):
    try:
        # Some error could happen when building the graph
        graph = Graph.from_payload(graph_data)
    except Exception as exc:
        logger.exception(exc)
        raise exc

    for i, vertex in enumerate(graph.generator_build(), 1):
        try:
            # 如果存在文件，当前不操作文件，避免重复操作
            if not process_file and vertex.base_type == 'documentloaders':
                template_dict = {
                    key: value
                    for key, value in vertex.data['node']['template'].items()
                    if isinstance(value, dict)
                }
                for key, value in template_dict.items():
                    if value.get('type') == 'fileNode':
                        # 过滤掉文件
                        vertex.params[key] = ''

            # vectore store 引入自动建库逻辑
            # 聊天窗口等flow 主动生成的vector 需要新建临时collection
            # tmp_{chat_id}
            if vertex.base_type == 'vectorstores':
                # 注入user_name
                vertex.params['user_name'] = kwargs.get('user_name') if kwargs else ''
                # 知识库通过参数传参
                if 'collection_name' in kwargs and 'collection_name' in vertex.params:
                    vertex.params['collection_name'] = kwargs['collection_name']
                if 'collection_name' in kwargs and 'index_name' in vertex.params:
                    vertex.params['index_name'] = kwargs['collection_name']

                if 'collection_name' in vertex.params and not vertex.params.get('collection_name'):
                    vertex.params['collection_name'] = f'tmp_{flow_id}_{chat_id if chat_id else 1}'
                    logger.info(f"rename_vector_col col={vertex.params['collection_name']}")
                    if process_file:
                        # L1 清除Milvus历史记录
                        vertex.params['drop_old'] = True
                elif 'index_name' in vertex.params and not vertex.params.get('index_name'):
                    # es
                    vertex.params['index_name'] = f'tmp_{flow_id}_{chat_id if chat_id else 1}'

            if vertex.base_type == 'chains' and 'retriever' in vertex.params:
                vertex.params['user_name'] = kwargs.get('user_name') if kwargs else ''

            vertex.build()
            params = vertex._built_object_repr()
            logger.debug(
                f"Building node {str(params)[:50]}{'...' if len(str(params)) > 50 else ''}")
            if vertex.artifacts:
                # The artifacts will be prompt variables
                # passed to build_input_keys_response
                # to set the input_keys values
                artifacts.update(vertex.artifacts)
        except Exception as exc:
            raise exc
    return graph


def access_check(payload: dict, owner_user_id: int, target_id: int, type: AccessType) -> bool:
    if payload.get('role') != 'admin':
        # role_access
        with next(get_session()) as session:
            role_access = session.exec(
                select(RoleAccess).where(RoleAccess.role_id.in_(payload.get('role')),
                                         RoleAccess.type == type.value)).all()
        third_ids = [access.third_id for access in role_access]
        if owner_user_id != payload.get('user_id') and str(target_id) not in third_ids:
            return False
    return True


def get_L2_param_from_flow(
    flow_data: dict,
    flow_id: str,
):
    graph = Graph.from_payload(flow_data)
    node_id = []
    variable_ids = []
    file_name = []
    for node in graph.nodes:
        if node.vertex_type in {'InputFileNode'}:
            node_id.append(node.id)
            file_name.append(node.params.get('file_type'))
        elif node.vertex_type in {'VariableNode'}:
            variable_ids.append(node.id)

    with session_getter() as session:
        db_variables = session.exec(select(Variable).where(Variable.flow_id == flow_id)).all()

        old_file_ids = {
            variable.node_id: variable
            for variable in db_variables if variable.value_type == 3
        }
        update = []
        delete_node_ids = []
        try:
            for index, id in enumerate(node_id):
                if id in old_file_ids:
                    if file_name[index] != old_file_ids.get(id).variable_name:
                        old_file_ids.get(id).variable_name = file_name[index]
                        update.append(old_file_ids.get(id))
                    old_file_ids.pop(id)
                else:
                    # file type
                    db_new_var = Variable(flow_id=flow_id,
                                          node_id=id,
                                          variable_name=file_name[index],
                                          value_type=3)
                    update.append(db_new_var)
            # delete variable which not delete by edit
            old_variable_ids = {
                variable.node_id
                for variable in db_variables if variable.value_type != 3
            }

            if old_file_ids:
                delete_node_ids.extend(list(old_file_ids.keys()))

            delete_node_ids.extend(old_variable_ids.difference(set(variable_ids)))

            if update:
                [session.add(var) for var in update]
            if delete_node_ids:
                session.exec(delete(Variable).where(Variable.node_id.in_(delete_node_ids)))
            session.commit()
            return True
        except Exception as e:
            logger.exception(e)
            session.rollback()
            return False
