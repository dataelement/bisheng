import asyncio
import functools
import hashlib
import importlib
import inspect
import io
import logging
import re
import time
import zipfile
from functools import wraps
from typing import Dict, Optional, Union, List, Tuple
from urllib.parse import urlparse

from bisheng.template.frontend_node.constants import FORCE_SHOW_FIELDS
from bisheng.utils import constants
from docstring_parser import parse  # type: ignore

logger = logging.getLogger(__name__)


def build_template_from_function(name: str, type_to_loader_dict: Dict, add_function: bool = False):
    classes = [item.__annotations__['return'].__name__ for item in type_to_loader_dict.values()]

    # Raise error if name is not in chains
    if name not in classes:
        raise ValueError(f'{name} not found')

    for _type, v in type_to_loader_dict.items():
        if v.__annotations__['return'].__name__ == name:
            _class = v.__annotations__['return']

            # Get the docstring
            docs = parse(_class.__doc__)

            variables = {'_type': _type}
            for class_field_items, value in _class.__fields__.items():
                if class_field_items in ['callback_manager']:
                    continue
                variables[class_field_items] = {}
                for name_, value_ in value.__repr_args__():
                    if name_ == 'default_factory':
                        try:
                            variables[class_field_items]['default'] = get_default_factory(
                                module=_class.__base__.__module__, function=value_)
                        except Exception:
                            variables[class_field_items]['default'] = None
                    elif name_ not in ['name']:
                        variables[class_field_items][name_] = value_

                variables[class_field_items]['placeholder'] = (
                    docs.params[class_field_items] if class_field_items in docs.params else '')
            # Adding function to base classes to allow
            # the output to be a function
            base_classes = get_base_classes(_class)
            if add_function:
                base_classes.append('function')

            return {
                'template': format_dict(variables, name),
                'description': docs.short_description or '',
                'base_classes': base_classes,
            }


def build_template_from_class(name: str, type_to_cls_dict: Dict, add_function: bool = False):
    classes = [item.__name__ for item in type_to_cls_dict.values()]

    # Raise error if name is not in chains
    if name not in classes:
        raise ValueError(f'{name} not found.')

    for _type, v in type_to_cls_dict.items():
        if v.__name__ == name:
            _class = v

            # Get the docstring
            docs = parse(_class.__doc__)

            variables = {'_type': _type}

            if getattr(_class, 'model_fields', None):
                for class_field_items, value in _class.model_fields.items():
                    if class_field_items in ['callback_manager']:
                        continue
                    variables[class_field_items] = {}
                    for name_, value_ in value.__repr_args__():
                        if name_ == 'default_factory':
                            try:
                                variables[class_field_items]['default'] = get_default_factory(
                                    module=_class.__base__.__module__, function=value_)
                            except Exception:
                                variables[class_field_items]['default'] = None
                        elif name_ not in ['name']:
                            variables[class_field_items][name_] = value_

                    variables[class_field_items]['placeholder'] = (
                        docs.params[class_field_items] if class_field_items in docs.params else '')
            else:
                for name, param in inspect.signature(_class.__init__).parameters.items():
                    if name == 'self':
                        continue
                    variables[name] = {}
                    variables[name]['default'] = get_default_factory(module=_class.__base__.__module__,
                                                                     function=str(param.annotation))
                    variables[name]['annotation'] = str(param.annotation)
                    variables[name]['required'] = False

            base_classes = get_base_classes(_class)
            # Adding function to base classes to allow
            # the output to be a function
            if add_function:
                base_classes.append('function')
            return {
                'template': format_dict(variables, name),
                'description': docs.short_description or '',
                'base_classes': base_classes,
            }
    return None


def build_template_from_method(
        class_name: str,
        method_name: str,
        type_to_cls_dict: Dict,
        add_function: bool = False,
):
    classes = [item.__name__ for item in type_to_cls_dict.values()]

    # Raise error if class_name is not in classes
    if class_name not in classes:
        raise ValueError(f'{class_name} not found.')

    for _type, v in type_to_cls_dict.items():
        if v.__name__ == class_name:
            _class = v

            # Check if the method exists in this class
            if not hasattr(_class, method_name):
                raise ValueError(f'Method {method_name} not found in class {class_name}')

            # Get the method
            method = getattr(_class, method_name)

            # Get the docstring
            docs = parse(method.__doc__)

            # Get the signature of the method
            sig = inspect.signature(method)

            # Get the parameters of the method
            params = sig.parameters

            # Initialize the variables dictionary with method parameters
            variables = {
                '_type': _type,
                **{
                    name: {
                        'default': param.default if param.default != param.empty else None,
                        'type': param.annotation if param.annotation != param.empty else None,
                        'required': param.default == param.empty,
                    }
                    for name, param in params.items() if name not in ['self', 'kwargs', 'args']
                },
            }

            base_classes = get_base_classes(_class)

            # Adding function to base classes to allow the output to be a function
            if add_function:
                base_classes.append('function')

            return {
                'template': format_dict(variables, class_name),
                'description': docs.short_description or '',
                'base_classes': base_classes,
            }


def get_base_classes(cls):
    """Get the base classes of a class.
    These are used to determine the output of the nodes.
    """
    if hasattr(cls, '__bases__') and cls.__bases__:
        bases = cls.__bases__
        result = []
        for base in bases:
            if any(type in base.__module__ for type in ['pydantic', 'abc']):
                continue
            result.append(base.__name__)
            base_classes = get_base_classes(base)
            # check if the base_classes are in the result
            # if not, add them
            for base_class in base_classes:
                if base_class not in result:
                    result.append(base_class)
    else:
        result = [cls.__name__]
    if not result:
        result = [cls.__name__]
    return list(set(result + [cls.__name__]))


def get_default_factory(module: str, function: str):
    pattern = r'<function (\w+)>'

    if match := re.search(pattern, function):
        imported_module = importlib.import_module(module)
        return getattr(imported_module, match[1])()
    return None


def type_to_string(tp):
    if getattr(tp, '__args__', None):
        args_str = ','.join(type_to_string(arg) for arg in tp.__args__
                            if arg is not type(None))  # noqa
        return f'{tp.__name__}[{args_str}]'
    else:
        return tp.__name__


def format_dict(d, name: Optional[str] = None):
    """
    Formats a dictionary by removing certain keys and modifying the
    values of other keys.

    Args:
        d: the dictionary to format
        name: the name of the class to format

    Returns:
        A new dictionary with the desired modifications applied.
    """
    need_remove_key = []
    # Process remaining keys
    for key, value in d.items():
        if key == '_type':
            continue

        _type = value['type'] if 'type' in value else value['annotation']

        if not isinstance(_type, str):
            _type = type_to_string(_type)

        # Remove 'Optional' wrapper
        if 'Optional' in _type:
            _type = _type.replace('Optional[', '')[:-1]
            value['required'] = False

        # Check for list type
        if 'List' in _type or 'Sequence' in _type or 'Set' in _type:
            _type = (_type.replace('List[', '').replace('Sequence[', '').replace('Set[', '')[:-1])
            value['list'] = True
        else:
            value['list'] = False

        # Replace 'Mapping' with 'dict'
        if 'Mapping' in _type:
            _type = _type.replace('Mapping', 'dict')

        # Change type from str to Tool
        value['type'] = 'Tool' if key in ['allowed_tools'] else _type

        value['type'] = 'int' if key in ['max_value_length'] else value['type']

        # Show or not field
        value['show'] = bool(
            (value['required'] and (key not in ['input_variables'] or name == 'SequentialChain'))
            or key in FORCE_SHOW_FIELDS or 'api_key' in key)

        # Add password field
        value['password'] = any(text in key.lower()
                                for text in ['password', 'token', 'api', 'key'])

        # Add multline
        value['multiline'] = key in [
            'suffix',
            'prefix',
            'template',
            'examples',
            'code',
            'headers',
            'format_instructions',
        ]

        # Replace dict type with str
        if 'dict' in value['type'].lower():
            value['type'] = 'code'

        if key == 'dict_':
            value['type'] = 'file'
            value['suffixes'] = ['.json', '.yaml', '.yml']
            value['fileTypes'] = ['json', 'yaml', 'yml']

        # Replace default value with actual value
        if 'default' in value:
            value['value'] = value['default']
            value.pop('default')

        if key == 'headers':
            value['value'] = """{'Authorization':
            'Bearer <token>'}"""
        # Add options to openai
        if name == 'OpenAI' and key == 'model_name':
            value['options'] = constants.OPENAI_MODELS
            value['list'] = True
            value['value'] = constants.OPENAI_MODELS[0]
        elif name == 'ChatOpenAI' and key == 'model_name':
            value['options'] = constants.CHAT_OPENAI_MODELS
            value['list'] = True
            value['value'] = constants.CHAT_OPENAI_MODELS[0]
        elif (name == 'Anthropic' or name == 'ChatAnthropic') and key == 'model_name':
            value['options'] = constants.ANTHROPIC_MODELS
            value['list'] = True
            value['value'] = constants.ANTHROPIC_MODELS[0]

        if 'value' in value and type(value['value']) == set:
            value['value'] = list(value['value'])
        if 'value' in value and inspect.isfunction(value['value']):
            need_remove_key.append(key)
    for one in need_remove_key:
        del d[one]
    return d


def update_verbose(d: dict, new_value: bool) -> dict:
    """
    Recursively updates the value of the 'verbose' key in a dictionary.

    Args:
        d: the dictionary to update
        new_value: the new value to set

    Returns:
        The updated dictionary.
    """

    for k, v in d.items():
        if isinstance(v, dict):
            update_verbose(v, new_value)
        elif k == 'verbose':
            d[k] = new_value
    return d


def sync_to_async(func):
    """
    Decorator to convert a sync function to an async function.
    """

    @wraps(func)
    async def async_wrapper(*args, **kwargs):
        return func(*args, **kwargs)

    return async_wrapper


def run_async(coro, loop=None):
    """
    Run asynchronous functions
    :param coro:
    :param loop:
    :return:
    """
    if loop is None:
        try:
            loop = asyncio.get_running_loop()
            return loop.run_until_complete(coro)
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(coro)

    return loop.run_until_complete(coro)


def get_cache_key(flow_id: str, chat_id: str, vertex_id: str = None):
    return f'{flow_id}_{chat_id}_{vertex_id}'


def _is_valid_url(url: str) -> bool:
    """Check if the url is valid."""
    parsed = urlparse(url)
    return bool(parsed.netloc) and bool(parsed.scheme)


# Retry decorator Asynchronous
def retry_async(num_retries=3, delay=0.5, return_exceptions=False):
    def wrapper(func):
        async def wrapped(*args, **kwargs):
            for i in range(num_retries):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    logger.info(
                        f"Retrying {func.__name__} in {delay} seconds... Attempt {i + 1} of {num_retries}... error: {e}")
                    if i == num_retries - 1:
                        if return_exceptions:
                            # Return Exception Parameters will bee.argsSplit into tuples
                            return e.args if len(e.args) > 1 else e.args[0]
                        logger.error(f"Failed to execute {func.__name__} after {num_retries} retries")
                        raise e
                    await asyncio.sleep(delay)
            return None

        return wrapped

    return wrapper


# Retry decorator
def retry_sync(num_retries=3, delay=0.5, return_exceptions=False):
    def wrapper(func):
        def wrapped(*args, **kwargs):
            for i in range(num_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    logger.info(
                        f"Retrying {func.__name__} in {delay} seconds... Attempt {i + 1} of {num_retries}... error: {e}")
                    if i == num_retries - 1:
                        if return_exceptions:
                            # Return Exception Parameters will bee.argsSplit into tuples
                            return e.args if len(e.args) > 1 else e.args[0]
                        logger.error(f"Failed to execute {func.__name__} after {num_retries} retries")
                        raise e
                    time.sleep(delay)
            return None

        return wrapped

    return wrapper


def calculate_md5(file: Union[str, bytes]):
    """Calculating the Document's MD5 .
    Returns:
        str: of the document MD5 .
    """
    md5_hash = hashlib.md5()

    if isinstance(file, bytes):
        md5_hash.update(file)
        return md5_hash.hexdigest()

    else:
        # Reading Files in Binary Form
        with open(file, "rb") as f:
            # Read files by block to avoid large files taking up too much memory
            for chunk in iter(lambda: f.read(4096), b""):
                md5_hash.update(chunk)

        return md5_hash.hexdigest()


async def async_calculate_md5(file: Union[str, bytes]):
    """of the asynchronous computation document MD5 .
    Returns:
        str: of the document MD5 .
    """
    import aiofiles

    md5_hash = hashlib.md5()

    if isinstance(file, bytes):
        md5_hash.update(file)
        return md5_hash.hexdigest()

    else:
        # Read files asynchronously in binary form
        async with aiofiles.open(file, "rb") as f:
            # Read files asynchronously by block to avoid large files taking up too much memory
            while True:
                chunk = await f.read(4096)
                if not chunk:
                    break
                md5_hash.update(chunk)

        return md5_hash.hexdigest()


# Read all files in the directory
def read_files_in_directory(path: str):
    """
    Reads all files in the directory and returns a list of filenames.
    Args:
        path (str): Directory Path
    Returns:
        list: List of filenames.
    """
    import os

    if not os.path.exists(path):
        logger.error(f"Path {path} does not exist.")
        return []

    files = []
    for root, _, filenames in os.walk(path):
        for filename in filenames:
            files.append(os.path.join(root, filename))
    return files


def sync_func_to_async(func, executor=None):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        loop = asyncio.get_running_loop()
        bound_func = functools.partial(func, *args, **kwargs)
        return await loop.run_in_executor(executor, bound_func)

    return wrapper


def bytes_to_zip(
        files: List[Tuple[str, bytes]],
        compress_level: int = 6
) -> bytes:
    """
    Package byte stream data intoZIPfiles, back toZIPByte Stream for Files

    Parameters:
        files: Contains(The file name, Byte Stream)List of tuples
        compress_level: compression level(0-9)，0Indicates no compression,9Represents the highest compression rate

    Return:
        Date GeneratedZIPFile Byte Stream
    """
    try:
        # Verify compression level
        if not 0 <= compress_level <= 9:
            raise ValueError("The compression level must be0to9Between")

        # Create in-memory byte streams for storageZIPDATA
        zip_buffer = io.BytesIO()

        # BuatZIPFile and add byte stream data
        with zipfile.ZipFile(
                zip_buffer,
                'w',
                zipfile.ZIP_DEFLATED,
                compresslevel=compress_level
        ) as zipf:
            for filename, data in files:
                # Enter your messageZIPAdd byte stream data to the file
                zipf.writestr(filename, data)
                print(f"Was added: {filename} (size: {len(data) / 1024:.2f} KB)")

        # will beZIPData is positioned to the starting position and returns a byte stream
        zip_buffer.seek(0)
        zip_data = zip_buffer.getvalue()

        logger.debug(f"\nZIPFile created successfully, total size: {len(zip_data) / 1024:.2f} KB")
        return zip_data

    except Exception as e:
        logger.error(f"Packaging process error: {str(e)}")
        raise e
