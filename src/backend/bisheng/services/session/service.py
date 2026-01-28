from bisheng.api.utils import build_flow_no_yield
from bisheng.core.cache.redis_manager import get_redis_client_sync
from bisheng.services.base import Service
from bisheng.services.session.utils import compute_dict_hash, session_id_generator

# if TYPE_CHECKING:
#     from bisheng.services.cache.base import BaseCacheService


class SessionService(Service):
    name = 'session_service'

    def __init__(self):
        self.cache_service = get_redis_client_sync()

    async def load_session(self, key, data_graph, **kwargs):
        # Check if the data is cached
        if key in self.cache_service:
            return await self.cache_service.aget(key)

        if key is None:
            key = self.generate_key(session_id=None, data_graph=data_graph)

        # If not cached, build the graph and cache it
        # graph, artifacts = await build_sorted_vertices(data_graph)
        # Complete with custom initialization methodsapiAlignment with Chat
        artifacts = {}
        graph = await build_flow_no_yield(graph_data=data_graph, **kwargs)

        await self.cache_service.aset(key, (graph, artifacts))

        return graph, artifacts

    def build_key(self, session_id, data_graph):
        json_hash = compute_dict_hash(data_graph)
        return f"{session_id}{'_' if session_id else ''}{json_hash}"

    def generate_key(self, session_id, data_graph):
        # Hash the JSON and combine it with the session_id to create a unique key
        if session_id is None:
            # generate a 5 char session_id to concatenate with the json_hash
            session_id = session_id_generator()
        return self.build_key(session_id, data_graph=data_graph).lower()

    def update_session(self, session_id, value):
        self.cache_service.set(session_id, value)

    def clear_session(self, session_id):
        self.cache_service.delete(session_id)
