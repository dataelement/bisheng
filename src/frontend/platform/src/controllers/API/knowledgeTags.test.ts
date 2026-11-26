import { beforeEach, expect, it, vi } from 'vitest';
import request from '../request';
import { createKnowledgeTagApi, deleteKnowledgeTagApi, getKnowledgeTagsApi, setFileTagsApi } from './knowledgeTags';
vi.mock('../request', () => ({ default: { get: vi.fn(), post: vi.fn(), delete: vi.fn() } }));
beforeEach(() => vi.clearAllMocks());
it('uses the space endpoints and adapts the tag list envelope', async () => {
 const tags = [{id: 4, name: 'Legal'}];
 vi.mocked(request.get).mockResolvedValue(tags);
 expect(await getKnowledgeTagsApi(7, {limit: 100}, true)).toEqual({data: tags, total: 1});
 expect(request.get).toHaveBeenCalledWith('/api/v1/knowledge/space/7/tag');
 await createKnowledgeTagApi(7, 'Finance', true);
 expect(request.post).toHaveBeenLastCalledWith('/api/v1/knowledge/space/7/tag', {tag_name: 'Finance'});
 await setFileTagsApi({knowledge_id: 7, file_id: 11, tag_ids: [4]}, true);
 expect(request.post).toHaveBeenLastCalledWith('/api/v1/knowledge/space/7/files/11/tag', {tag_ids: [4]});
 await deleteKnowledgeTagApi(7, 4, true);
 expect(request.delete).toHaveBeenCalledWith('/api/v1/knowledge/space/7/tag', {data: {tag_id: 4}});
});
it('preserves the ordinary library tag endpoints', async () => {
 await setFileTagsApi({knowledge_id: 8, file_id: 12, tag_ids: [5]});
 expect(request.post).toHaveBeenCalledWith('/api/v1/knowledge/file/tags', {knowledge_id: 8, file_id: 12, tag_ids: [5]});
});
