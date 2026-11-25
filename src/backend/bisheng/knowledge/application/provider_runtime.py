"""Request-scoped composition shared by web requests and worker invocations."""
from contextlib import AsyncExitStack, asynccontextmanager
from operator import eq, gt, lt
from urllib.parse import quote

import httpx

from bisheng.knowledge.application.provider_resolver import CapabilityUnavailable
from bisheng.knowledge.application.provider_retrieval import ProviderRetrieval, WeKnoraSearchPort


class WeKnoraDocumentSearchPort(WeKnoraSearchPort):
    """Read current document facts for the already authorized positive list only.

    GET knowledge/:id populates tags. The batch endpoint does not join them;
    the detail service can return null on join failure, so null is not [].
    No provider content/relations are cached across the post-recall check.
    """

    async def constrain(self, ids, tags, selection):
        if not tags and not selection.metadata:
            return ids
        operators = {'eq': eq, 'gt': gt, 'lt': lt}
        for predicate in selection.metadata:
            types = (int, float, str, bool) if predicate.operator == 'eq' else (int, float)
            if not predicate.field or predicate.operator not in operators or type(predicate.value) not in types:
                raise CapabilityUnavailable('unsupported metadata comparison')
        result = set()
        for remote in sorted(ids):
            if remote in {'.', '..'}:
                raise ValueError('invalid provider document locator')
            try:
                response = await self.client.get('knowledge/' + quote(remote, safe=''), follow_redirects=False)
            except httpx.RequestError:
                raise RuntimeError('provider document facts unavailable') from None
            if response.status_code != 200:
                raise RuntimeError('provider document facts unavailable')
            envelope = response.json()
            row = envelope.get('data') if isinstance(envelope, dict) and envelope.get('success') is True else None
            if (not isinstance(row, dict) or row.get('id') != remote or row.get('knowledge_base_id') != self.route.remote_kb_id or str(row.get('tenant_id')) != self.route.remote_scope_id):
                raise ValueError('invalid provider document facts')
            if tags:
                relations = row.get('tags')
                if not isinstance(relations, list) or not all(isinstance(t, dict) and isinstance(t.get('id'), str) and t.get('knowledge_base_id') == self.route.remote_kb_id for t in relations):
                    raise CapabilityUnavailable('incomplete provider tag relations')
                present = {t['id'] for t in relations}
                if not (all if selection.tag_mode == 'all' else any)(t in present for t in tags):
                    continue
            if selection.metadata:
                values = row.get('custom_metadata')
                if not isinstance(values, dict):
                    raise CapabilityUnavailable('incomplete provider metadata')
                if not all(type(values.get(p.field)) is type(p.value) and operators[p.operator](values[p.field], p.value) for p in selection.metadata):
                    continue
            result.add(remote)
        return result


@asynccontextmanager
async def request_provider_retrieval(*, repository=None, client_factory=None):
    async with AsyncExitStack() as stack:
        async def port(route):
            if route.provider_key != 'weknora' or route.capability_revision <= 0:
                raise CapabilityUnavailable('provider retrieval not verified')
            factory = client_factory
            if factory is None:
                from bisheng.knowledge.application.provider_v1_runtime import instance_client
                factory = instance_client
            client = await stack.enter_async_context(factory(route))
            return WeKnoraDocumentSearchPort(client, route)

        yield ProviderRetrieval(port, repository=repository)
