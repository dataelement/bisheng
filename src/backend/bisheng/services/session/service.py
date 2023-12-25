from bisheng.cache.redis import redis_client
from bisheng.interface.run import build_sorted_vertices
from bisheng.services.base import Service
from bisheng.services.session.utils import compute_dict_hash, session_id_generator

# if TYPE_CHECKING:
#     from bisheng.services.cache.base import BaseCacheService


class SessionService(Service):
    name = 'session_service'

    def __init__(self):
        self.cache_service = redis_client

    async def load_session(self, key, data_graph):
        # Check if the data is cached
        if key in self.cache_service:
            return self.cache_service.get(key)

        if key is None:
            key = self.generate_key(session_id=None, data_graph=data_graph)

        # If not cached, build the graph and cache it
        graph, artifacts = await build_sorted_vertices(data_graph)

        self.cache_service.set(key, (graph, artifacts))

        return graph, artifacts

    def build_key(self, session_id, data_graph):
        json_hash = compute_dict_hash(data_graph)
        return f"{session_id}{':' if session_id else ''}{json_hash}"

    def generate_key(self, session_id, data_graph):
        # Hash the JSON and combine it with the session_id to create a unique key
        if session_id is None:
            # generate a 5 char session_id to concatenate with the json_hash
            session_id = session_id_generator()
        return self.build_key(session_id, data_graph=data_graph)

    def update_session(self, session_id, value):
        self.cache_service.set(session_id, value)

    def clear_session(self, session_id):
        self.cache_service.delete(session_id)
