import asyncio
import json
from pathlib import Path
from typing import Any, Coroutine, Dict, List, Optional, Tuple, Union

from bisheng.database.base import session_getter
from bisheng.database.models.message import ChatMessage
from bisheng.database.models.report import Report as ReportModel
from bisheng.interface.run import build_sorted_vertices, get_memory_key, update_memory_keys
from bisheng.services.deps import get_session_service
from bisheng.template.field.base import TemplateField
from bisheng.utils.docx_temp import test_replace_string
from bisheng.utils.logger import logger
from bisheng.utils.minio_client import MinioClient
from bisheng_langchain.input_output import Report
from langchain.chains.base import Chain
from langchain.schema import AgentAction, Document
from langchain.vectorstores.base import VectorStore
from pydantic import BaseModel
from sqlmodel import select


def fix_memory_inputs(langchain_object):
    """
    Given a LangChain object, this function checks if it has a memory attribute and if that memory key exists in the
    object's input variables. If so, it does nothing. Otherwise, it gets a possible new memory key using the
    get_memory_key function and updates the memory keys using the update_memory_keys function.
    """
    if not hasattr(langchain_object, 'memory') or langchain_object.memory is None:
        return
    try:
        if (hasattr(langchain_object.memory, 'memory_key')
                and langchain_object.memory.memory_key in langchain_object.input_variables):
            return
    except AttributeError:
        input_variables = (langchain_object.prompt.input_variables if hasattr(
            langchain_object, 'prompt') else langchain_object.input_keys)
        if langchain_object.memory.memory_key in input_variables:
            return

    possible_new_mem_key = get_memory_key(langchain_object)
    if possible_new_mem_key is not None:
        update_memory_keys(langchain_object, possible_new_mem_key)


def format_actions(actions: List[Tuple[AgentAction, str]]) -> str:
    """Format a list of (AgentAction, answer) tuples into a string."""
    output = []
    for action, answer in actions:
        log = action.log
        tool = action.tool
        tool_input = action.tool_input
        output.append(f'Log: {log}')
        if 'Action' not in log and 'Action Input' not in log:
            output.append(f'Tool: {tool}')
            output.append(f'Tool Input: {tool_input}')
        output.append(f'Answer: {answer}')
        output.append('')  # Add a blank line
    return '\n'.join(output)


def get_result_and_thought(langchain_object: Any, inputs: dict):
    """Get result and thought from extracted json"""
    try:
        if hasattr(langchain_object, 'verbose'):
            langchain_object.verbose = True

        if hasattr(langchain_object, 'return_intermediate_steps'):
            langchain_object.return_intermediate_steps = True

        fix_memory_inputs(langchain_object)

        try:
            # all use chat handlers
            # action = 'default'
            from bisheng.api.v1 import callback
            callbacks = [callback.StreamingLLMCallbackHandler(None, flow_id=None, chat_id=None)]
            output = langchain_object(inputs, return_only_outputs=True, callbacks=callbacks)
        except ValueError as exc:
            # make the error message more informative
            logger.debug(f'Error: {str(exc)}')
            raise exc

    except Exception as exc:
        raise ValueError(f'Error: {str(exc)}') from exc
    return output


def get_input_str_if_only_one_input(inputs: dict) -> Optional[str]:
    """Get input string if only one input is provided"""
    return list(inputs.values())[0] if len(inputs) == 1 else None


def get_build_result(data_graph, session_id):
    # If session_id is provided, load the langchain_object from the session
    # using build_sorted_vertices_with_caching.get_result_by_session_id
    # if it returns something different than None, return it
    # otherwise, build the graph and return the result
    if session_id:
        logger.debug(f'Loading LangChain object from session {session_id}')
        result = build_sorted_vertices(data_graph=data_graph)
        if result is not None:
            logger.debug('Loaded LangChain object')
            return result

    logger.debug('Building langchain object')
    return build_sorted_vertices(data_graph)


def process_inputs(inputs: Optional[dict], artifacts: Dict[str, Any], input_key: str) -> dict:
    if inputs is None:
        inputs = {}

    for key, value in artifacts.items():
        if key == 'repr':
            continue
        elif key not in inputs or not inputs[key]:
            inputs[key] = value
    # 针对api设置default input，防止技能变更后，输入变化
    if input_key not in inputs and 'default_input' in inputs:
        inputs[input_key] = inputs.pop('default_input')
    elif 'default_input' in inputs:
        inputs.pop('default_input')
    return inputs


def generate_result(langchain_object: Union[Chain, VectorStore], inputs: dict):
    if isinstance(langchain_object, Chain):
        if inputs is None:
            raise ValueError('Inputs must be provided for a Chain')
        logger.debug('Generating result and thought')
        result = get_result_and_thought(langchain_object, inputs)

        logger.debug('Generated result and thought')
    elif isinstance(langchain_object, VectorStore):
        result = langchain_object.search(**inputs)
    elif isinstance(langchain_object, Document):
        result = langchain_object.dict()
    else:
        logger.warning(f'Unknown langchain_object type: {type(langchain_object)}')
        if isinstance(langchain_object, Coroutine):
            result = asyncio.run(langchain_object)
        result = langchain_object

    return result


class Result(BaseModel):
    result: Any = None
    session_id: str


async def process_graph_cached(
    data_graph: Dict[str, Any],
    inputs: Optional[dict] = None,
    clear_cache=False,
    session_id=None,
    flow_id=None,
    history_count=10,
) -> Result:
    session_service = get_session_service()
    if clear_cache:
        session_service.clear_session(session_id)
    if session_id is None:
        session_id = session_service.generate_key(session_id=session_id, data_graph=data_graph)
    # Load the graph using SessionService
    session = await session_service.load_session(session_id,
                                                 data_graph,
                                                 artifacts={},
                                                 process_file=True,
                                                 flow_id=flow_id,
                                                 chat_id=session_id)
    graph, artifacts = session if session else (None, None)
    if not graph:
        raise ValueError('Graph not found in the session')
    built_object = await graph.abuild()
    input_key_object = built_object.input_keys[0]
    # memery input
    if hasattr(built_object, 'memory') and built_object.memory is not None:
        fix_memory_inputs(built_object)
        with session_getter() as session:
            history = session.exec(
                select(ChatMessage).where(
                    ChatMessage.chat_id == session_id,
                    ChatMessage.category.in_(['question', 'answer'])).order_by(
                        ChatMessage.id.desc()).limit(history_count)).all()
        history = list(reversed(history))
        next_loop = -1
        for index, chat_message in enumerate(history):
            if index + 1 >= len(history):
                continue
            if index <= next_loop:
                continue
            if not chat_message.is_bot and history[index + 1].is_bot:
                next_loop = index + 1
                if not chat_message.message or not chat_message.message.startswith('{'):
                    continue
                inputs_hsitory = json.loads(chat_message.message)
                outputs_history = {built_object.output_keys[0]: history[next_loop].message}
                built_object.memory.save_context(inputs_hsitory, outputs_history)
    if isinstance(built_object, Report):
        processed_inputs = process_inputs(inputs, artifacts or {}, input_key_object)
        result = generate_result(built_object, processed_inputs)
        # build report
        with session_getter() as db_session:
            template = db_session.exec(
                select(ReportModel).where(ReportModel.flow_id == flow_id).order_by(
                    ReportModel.id.desc())).first()
        if not template:
            logger.error('template not found flow_id={}', flow_id)
            raise ValueError(f'template not found flow_id={flow_id}')
        minio_client = MinioClient()
        template_muban = minio_client.get_share_link(template.object_name)
        report_name = built_object.report_name
        report_name = report_name if report_name.endswith('.docx') else f'{report_name}.docx'
        result = (result.get(built_object.output_keys[0]) if isinstance(result, dict) else result)
        test_replace_string(template_muban, result, report_name)
        result = {built_object.output_keys[0]: minio_client.get_share_link(report_name)}
    elif any(
        (vertex.id.startswith('InputNode')
         for vertex in graph.vertices)) and (not inputs
                                             or all(len(ins) == 0 for ins in inputs.values())):
        input_batch = []
        for vertex in graph.vertices:
            if vertex.id.startswith('InputNode'):
                questions = await vertex.get_result()
                for question in questions:
                    input_batch.append({built_object.input_keys[0]: question})
        report = ''
        for question in input_batch:
            logger.info('produce auto question question={}', question)
            processed_inputs = process_inputs(question, artifacts or {}, input_key_object)
            result = generate_result(built_object, processed_inputs)
            report = f"""{report}### {question} \n {result} \n """
        result = report
    else:
        processed_inputs = process_inputs(inputs, artifacts or {}, input_key_object)
        result = generate_result(built_object, processed_inputs)

    # langchain_object is now updated with the new memory
    # we need to update the cache with the updated langchain_object
    session_service.update_session(session_id, (graph, artifacts))

    return Result(result=result, session_id=session_id)


async def load_flow_from_json(flow: Union[Path, str, dict],
                              tweaks: Optional[dict] = None,
                              build=True):
    """
    Load flow from a JSON file or a JSON object.

    :param flow: JSON file path or JSON object
    :param tweaks: Optional tweaks to be processed
    :param build: If True, build the graph, otherwise return the graph object
    :return: Langchain object or Graph object depending on the build parameter
    """
    # If input is a file path, load JSON from the file
    if isinstance(flow, (str, Path)):
        with open(flow, 'r', encoding='utf-8') as f:
            flow_graph = json.load(f)
    # If input is a dictionary, assume it's a JSON object
    elif isinstance(flow, dict):
        flow_graph = flow
    else:
        raise TypeError('Input must be either a file path (str) or a JSON object (dict)')

    graph_data = flow_graph['data']
    if tweaks is not None:
        graph_data = process_tweaks(graph_data, tweaks)
    from bisheng.api.utils import build_flow_no_yield
    graph = await build_flow_no_yield(graph_data=graph_data,
                                      artifacts={},
                                      process_file=True,
                                      flow_id='tmp',
                                      chat_id=None)

    if build:
        langchain_object = graph.build()
        for object in langchain_object:
            if hasattr(object._built_object, 'input_keys'):
                langchain_object = object._built_object
                break

        if hasattr(langchain_object, 'verbose'):
            langchain_object.verbose = True

        if hasattr(langchain_object, 'return_intermediate_steps'):
            # Deactivating until we have a frontend solution
            # to display intermediate steps
            langchain_object.return_intermediate_steps = False

        fix_memory_inputs(langchain_object)
        return langchain_object

    return graph


def validate_input(graph_data: Dict[str, Any],
                   tweaks: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not isinstance(graph_data, dict) or not isinstance(tweaks, dict):
        raise ValueError('graph_data and tweaks should be dictionaries')

    nodes = graph_data.get('data', {}).get('nodes') or graph_data.get('nodes')

    if not isinstance(nodes, list):
        raise ValueError(
            "graph_data should contain a list of nodes under 'data' key or directly under 'nodes' key"
        )

    return nodes


def apply_tweaks(node: Dict[str, Any], node_tweaks: Dict[str, Any]) -> None:
    template_data = node.get('data', {}).get('node', {}).get('template')

    if not isinstance(template_data, dict):
        logger.warning(f"Template data for node {node.get('id')} should be a dictionary")
        return

    for tweak_name, tweak_value in node_tweaks.items():
        if tweak_name and tweak_value and tweak_name in template_data:
            key = tweak_name if tweak_name == 'file_path' else 'value'
            template_data[tweak_name][key] = tweak_value
        elif tweak_name and tweak_value:
            template_data[tweak_name] = TemplateField(field_type=type(tweak_value).__name__,
                                                      name=tweak_name,
                                                      value=tweak_value).to_dict()


def process_tweaks(graph_data: Dict[str, Any], tweaks: Dict[str, Dict[str,
                                                                      Any]]) -> Dict[str, Any]:
    """
    This function is used to tweak the graph data using the node id and the tweaks dict.

    :param graph_data: The dictionary containing the graph data. It must contain a 'data' key with
                       'nodes' as its child or directly contain 'nodes' key. Each node should have an 'id' and 'data'.
    :param tweaks: A dictionary where the key is the node id and the value is a dictionary of the tweaks.
                   The inner dictionary contains the name of a certain parameter as the key and the value to be tweaked.

    :return: The modified graph_data dictionary.

    :raises ValueError: If the input is not in the expected format.
    """
    nodes = validate_input(graph_data, tweaks)

    for node in nodes:
        if isinstance(node, dict) and isinstance(node.get('id'), str):
            node_id = node['id']
            if node_tweaks := tweaks.get(node_id):
                apply_tweaks(node, node_tweaks)
        else:
            logger.warning("Each node should be a dictionary with an 'id' key of type str")

    return graph_data
