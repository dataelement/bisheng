"""Project only visible, generation-bound local file metadata into the existing v1 envelopes."""
from hashlib import sha256
import json

from bisheng.common.errcode.knowledge_space import KnowledgeSpaceInvalidCursorError
from bisheng.knowledge.application.provider_v1_runtime import ProviderFeatureUnavailable, build_provider_reads
from bisheng.knowledge.domain.models.knowledge_space_file import _compute_ext_rank_python


async def listing(actor, route, *, parent_id, order_field, order_sort, page_size, search=False, page=1, cursor=None, file_ids=None, file_status=None, file_type=None, keyword=None, tag_ids=None):
    # Native body search uses ES and Native tag IDs are not external tag refs.
    if keyword or tag_ids or not 1 <= page_size <= 200 or page < 1 or file_type not in (None,0,1):
        raise ProviderFeatureUnavailable()
    facts = await (await build_provider_reads()).visible_facts(actor,route.space_id,parent_id)
    parents = {r.resource_id:r.parent_id for r in facts if r.kind=='folder'}
    def in_scope(r):
        if not search: return r.parent_id==parent_id
        if parent_id is None: return True
        seen=set()
        p=r.parent_id
        while p is not None and p not in seen:
            if p==parent_id: return True
            seen.add(p); p=parents.get(p)
        return False
    rows=[dict(id=r.resource_id, knowledge_id=route.space_id,file_name=r.name,file_type=int(r.kind!='folder'),file_size=r.file_size,status=r.status,create_time=r.create_time,update_time=r.update_time) for r in facts if in_scope(r) and (not file_ids or r.resource_id in file_ids) and (not file_status or r.status in file_status) and (file_type is None or file_type==int(r.kind!='folder'))]
    # Tie breaks are always descending (updated, id), matching the Native file-type cursor.
    rows.sort(key=lambda r:(r['update_time'] is not None,r['update_time'],r['id']), reverse=True)
    rows.sort(key=lambda r:(r['file_type'], _compute_ext_rank_python(r['file_name'])) if order_field=='file_type' else (r[order_field] is not None,r[order_field]),reverse=order_sort.lower()=='desc')
    offset=(page-1)*page_size
    fingerprint=sha256(json.dumps([actor.user_id,route.tenant_id,route.space_id,route.generation,parent_id,order_field,order_sort,file_ids,file_status,file_type]).encode()).hexdigest()[:24]
    if cursor:
        token,sep,last=cursor.partition(':')
        if token!=fingerprint or not sep or not last.isascii() or not last.isdigit(): raise KnowledgeSpaceInvalidCursorError()
        offset=next((i+1 for i,r in enumerate(rows) if str(r['id'])==last),None)
        if offset is None: raise KnowledgeSpaceInvalidCursorError()
    data=rows[offset:offset+page_size]
    more=offset+len(data)<len(rows)
    result=dict(data=data,page_size=page_size,has_more=more)
    if search: result.update(page=page,total=len(rows))
    else: result['next_cursor']=f'{fingerprint}:{data[-1]["id"]}' if more else None
    return result
