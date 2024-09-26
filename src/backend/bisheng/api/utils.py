import hashlib
import json
import xml.dom.minidom
from pathlib import Path
from typing import Dict, List

import aiohttp
from bisheng.api.v1.schemas import StreamData
from bisheng.database.base import session_getter
from bisheng.database.models.variable_value import Variable
from bisheng.graph.graph.base import Graph
from bisheng.utils.logger import logger
from fastapi import Request, WebSocket
from fastapi_jwt_auth import AuthJWT
from platformdirs import user_cache_dir
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


async def build_flow(graph_data: dict,
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

    number_of_nodes = len(graph.vertices)

    for i, vertex in enumerate(graph.generator_build(), 1):
        try:
            log_dict = {
                'log': f'Building node {vertex.vertex_type}',
            }
            yield str(StreamData(event='log', data=log_dict))
            # # 如果存在文件，当前不操作文件，避免重复操作
            if not process_file and (vertex.base_type == 'documentloaders'
                                     or vertex.base_type == 'input_output'):
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

                # 临时目录处理 tmp_{embeding}_{loader}_{chat_id}
                if 'collection_name' in vertex.params and not vertex.params.get('collection_name'):
                    vertex.params['collection_name'] = f'tmp_{flow_id}_{chat_id if chat_id else 1}'
                elif 'index_name' in vertex.params and not vertex.params.get('index_name'):
                    # es
                    vertex.params['index_name'] = f'tmp_{flow_id}_{chat_id if chat_id else 1}'

            await vertex.build(user_id=graph_data.get('user_id'))
            params = vertex._built_object_repr()
            valid = True
            logger.debug(
                f"Building node {vertex.vertex_type} {str(params)[:50]}{'...' if len(str(params)) > 50 else ''}"
            )
            if vertex.artifacts:
                # The artifacts will be prompt variables
                # passed to build_input_keys_response
                # to set the input_keys values
                artifacts.update(vertex.artifacts)
        except Exception as exc:
            logger.exception(f'Error building node {vertex.id}', exc_info=True)
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
    yield graph


async def build_flow_no_yield(graph_data: dict,
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
    sorted_vertices = graph.topological_sort()
    for vertex in sorted_vertices:
        try:
            # 如果存在文件，当前不操作文件，避免重复操作
            if not process_file and (vertex.base_type == 'documentloaders'
                                     or vertex.base_type == 'input_output'):
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
                if vertex.vertex_type not in [
                        'MilvusWithPermissionCheck', 'ElasticsearchWithPermissionCheck'
                ]:
                    # 知识库通过参数传参
                    if 'collection_name' in kwargs and 'collection_name' in vertex.params:
                        vertex.params['collection_name'] = kwargs['collection_name']
                    if 'collection_name' in kwargs and 'index_name' in vertex.params:
                        vertex.params['index_name'] = kwargs['collection_name']

                    if 'collection_name' in vertex.params and not vertex.params.get(
                            'collection_name'):
                        vertex.params[
                            'collection_name'] = f'tmp_{flow_id}_{chat_id if chat_id else 1}'
                        logger.info(f"rename_vector_col col={vertex.params['collection_name']}")
                        if process_file:
                            # L1 清除Milvus历史记录
                            vertex.params['drop_old'] = True
                    elif 'index_name' in vertex.params and not vertex.params.get('index_name'):
                        # es
                        vertex.params['index_name'] = f'tmp_{flow_id}_{chat_id if chat_id else 1}'

            if vertex.base_type == 'chains' and 'retriever' in vertex.params:
                vertex.params['user_name'] = kwargs.get('user_name') if kwargs else ''

            await vertex.build()
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


async def check_permissions(Authorize: AuthJWT, roles: List[str]):
    Authorize.jwt_required()
    payload = json.loads(Authorize.get_jwt_subject())
    user_roles = [payload.get('role')] if isinstance(payload.get('role'),
                                                     str) else payload.get('role')
    if any(role in roles for role in user_roles):
        return True
    else:
        raise ValueError('权限不够')


def get_L2_param_from_flow(flow_data: dict, flow_id: str, version_id: int = None):
    graph = Graph.from_payload(flow_data)
    node_id = []
    variable_ids = []
    file_name = []
    for node in graph.vertices:
        if node.vertex_type in {'InputFileNode'}:
            node_id.append(node.id)
            file_name.append(node.params.get('file_type'))
        elif node.vertex_type in {'VariableNode'}:
            variable_ids.append(node.id)

    with session_getter() as session:
        db_variables = session.exec(
            select(Variable).where(Variable.flow_id == flow_id,
                                   Variable.version_id == version_id)).all()

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
                                          version_id=version_id,
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
                session.exec(
                    delete(Variable).where(Variable.node_id.in_(delete_node_ids),
                                           version_id == version_id, flow_id == flow_id))
            session.commit()
            return True
        except Exception as e:
            logger.exception(e)
            session.rollback()
            return False


def raw_frontend_data_is_valid(raw_frontend_data):
    """Check if the raw frontend data is valid for processing."""
    return 'template' in raw_frontend_data and 'display_name' in raw_frontend_data


def is_valid_data(frontend_node, raw_frontend_data):
    """Check if the data is valid for processing."""

    return frontend_node and 'template' in frontend_node and raw_frontend_data_is_valid(
        raw_frontend_data)


def update_template_values(frontend_template, raw_template):
    """Updates the frontend template with values from the raw template."""
    for key, value_dict in raw_template.items():
        if key == 'code' or not isinstance(value_dict, dict):
            continue

        update_template_field(frontend_template, key, value_dict)


def get_file_path_value(file_path):
    """Get the file path value if the file exists, else return empty string."""
    try:
        path = Path(file_path)
    except TypeError:
        return ''

    # Check for safety
    # If the path is not in the cache dir, return empty string
    # This is to prevent access to files outside the cache dir
    # If the path is not a file, return empty string
    if not path.exists() or not str(path).startswith(user_cache_dir('bisheng', 'bisheng')):
        return ''
    return file_path


def update_template_field(frontend_template, key, value_dict):
    """Updates a specific field in the frontend template."""
    template_field = frontend_template.get(key)
    if not template_field or template_field.get('type') != value_dict.get('type'):
        return

    if 'value' in value_dict and value_dict['value']:
        template_field['value'] = value_dict['value']

    if 'file_path' in value_dict and value_dict['file_path']:
        file_path_value = get_file_path_value(value_dict['file_path'])
        if not file_path_value:
            # If the file does not exist, remove the value from the template_field["value"]
            template_field['value'] = ''
        template_field['file_path'] = file_path_value


def update_frontend_node_with_template_values(frontend_node, raw_frontend_node):
    """
    Updates the given frontend node with values from the raw template data.

    :param frontend_node: A dict representing a built frontend node.
    :param raw_template_data: A dict representing raw template data.
    :return: Updated frontend node.
    """
    if not is_valid_data(frontend_node, raw_frontend_node):
        return frontend_node

    # Check if the display_name is different than "CustomComponent"
    # if so, update the display_name in the frontend_node
    if raw_frontend_node['display_name'] != 'CustomComponent':
        frontend_node['display_name'] = raw_frontend_node['display_name']

    update_template_values(frontend_node['template'], raw_frontend_node['template'])

    return frontend_node


def parse_server_host(endpoint: str):
    """ 将数据库中的endpoints解析为http请求的host """
    endpoint = endpoint.replace('http://', '').split('/')[0]
    return f'http://{endpoint}'


# 将 nvidia-smi -q  -x 的输出解析为可视化数据
def parse_gpus(gpu_str: str) -> List[Dict]:
    dom_tree = xml.dom.minidom.parseString(gpu_str)
    collections = dom_tree.documentElement
    gpus = collections.getElementsByTagName('gpu')
    res = []
    for one in gpus:
        fb_mem_elem = one.getElementsByTagName('fb_memory_usage')[0]
        gpu_uuid_elem = one.getElementsByTagName('uuid')[0]
        gpu_id_elem = one.getElementsByTagName('minor_number')[0]
        gpu_total_mem = fb_mem_elem.getElementsByTagName('total')[0]
        free_mem = fb_mem_elem.getElementsByTagName('free')[0]
        gpu_utility_elem = one.getElementsByTagName('utilization')[0].getElementsByTagName(
            'gpu_util')[0]
        res.append({
            'gpu_uuid':
            gpu_uuid_elem.firstChild.data,
            'gpu_id':
            gpu_id_elem.firstChild.data,
            'gpu_total_mem':
            '%.2f G' % (float(gpu_total_mem.firstChild.data.split(' ')[0]) / 1024),
            'gpu_used_mem':
            '%.2f G' % (float(free_mem.firstChild.data.split(' ')[0]) / 1024),
            'gpu_utility':
            round(float(gpu_utility_elem.firstChild.data.split(' ')[0]) / 100, 2)
        })
    return res


async def get_url_content(url: str) -> str:
    """ 获取接口的返回的body内容 """
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status != 200:
                raise Exception(f'Failed to download content, HTTP status code: {response.status}')
            res = await response.read()
            return res.decode('utf-8')


def get_request_ip(request: Request | WebSocket) -> str:
    """ 获取客户端真实IP """
    x_forwarded_for = request.headers.get('X-Forwarded-For')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0]
    return request.client.host


def md5_hash(original_string: str):
    md5 = hashlib.md5()
    md5.update(original_string.encode('utf-8'))
    return md5.hexdigest()
