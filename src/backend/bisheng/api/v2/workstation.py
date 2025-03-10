from bisheng.api.services import knowledge_imp, llm
from bisheng.api.services.knowledge import KnowledgeService
from bisheng.api.services.user_service import UserPayload
from bisheng.api.v1.schemas import KnowledgeFileOne, KnowledgeFileProcess, resp_200
from bisheng.cache.utils import save_download_file
from bisheng.database.models.knowledge import KnowledgeCreate, KnowledgeDao, KnowledgeTypeEnum
from fastapi import APIRouter, BackgroundTasks, Body, File, Request, UploadFile

router = APIRouter(prefix='/workstation', tags=['OpenAPI', 'Chat'])


@router.post('/parsefile')
def parseFile(file: UploadFile = File(...)):
    knowledge_imp.read_chunk_text


@router.post('/knowledgeUpload')
async def knowledgeUpload(
        request: Request,
        background_tasks: BackgroundTasks,
        file: UploadFile = File(...),
        uid: int = Body(...),
):
    # 查询是否有个人知识库
    knowledge = KnowledgeDao.get_user_knowledge(uid, None, KnowledgeTypeEnum.PRIVATE)[0]
    if not knowledge:
        model = llm.LLMService.get_knowledge_llm()
        knowledgeCreate = KnowledgeCreate(name='个人知识库',
                                          type=KnowledgeTypeEnum.PRIVATE.value,
                                          user_id=uid,
                                          model=model.embedding_model_id)

        knowledge = KnowledgeService.create_knowledge(request, UserPayload(user_id=uid),
                                                      knowledgeCreate)

    file_byte = await file.read()
    file_path = save_download_file(file_byte, 'bisheng', file.filename)
    req_data = KnowledgeFileProcess(knowledge_id=knowledge.id,
                                    file_list=[KnowledgeFileOne(file_path=file_path)])
    res = KnowledgeService.process_knowledge_file(request, UserPayload(user_id=uid),
                                                  background_tasks, req_data)
    return resp_200(data=res[0])


@router.get('/queryKnowledge')
def queryKnoledgeList(request: Request, uid: int, page: int, size: int):
    # 查询是否有个人知识库
    knowledge = KnowledgeDao.get_user_knowledge(uid, None, KnowledgeTypeEnum.PRIVATE)
    if not knowledge:
        return resp_200(data={'total': 0, 'list': []})
    res, total, _ = KnowledgeService.get_knowledge_files(request,
                                                         UserPayload(user_id=uid),
                                                         knowledge[0].id,
                                                         page=page,
                                                         page_size=size)
    return resp_200(data={'list': res, 'total': total})


@router.delete('/deleteKnowledge')
def deleteKnowledge(request: Request, uid: int, file_id: int):
    res = KnowledgeService.delete_knowledge_file(request, UserPayload(user_id=uid), [file_id])
    return resp_200(data=res)


@router.get('/knowledgeQuery')
def knowledgeQuery(request: Request, uid: int, query: str):
    knowledge = KnowledgeDao.get_user_knowledge(uid, None, KnowledgeTypeEnum.PRIVATE)
    if not knowledge:
        return resp_200(data=query)

    search_kwargs = {'partition_key': knowledge[0].id}
    embedding = knowledge_imp.decide_embeddings(knowledge[0].model)
    vectordb = knowledge_imp.decide_vectorstores(knowledge[0].collection_name, 'Milvus', embedding)
    vectordb.partition_key = knowledge[0].id
    content = vectordb.as_retriever(search_kwargs=search_kwargs)._get_relevant_documents(
        query, run_manager=None)
    if content:
        content = [c.page_content for c in content]
    else:
        content = []

    return resp_200(data='\n'.join(content))
