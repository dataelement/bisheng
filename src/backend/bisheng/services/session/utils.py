import hashlib
import random
import string

from bisheng.common.utils.util import orjson_dumps
from bisheng.core.cache.utils import filter_json


def session_id_generator(size=6):
    return ''.join(random.SystemRandom().choices(string.ascii_uppercase + string.digits, k=size))


def compute_dict_hash(graph_data):
    graph_data = filter_json(graph_data)

    cleaned_graph_json = orjson_dumps(graph_data, sort_keys=True)

    return hashlib.sha256(cleaned_graph_json.encode('utf-8')).hexdigest()
