import request from "./request";

// 毕昇config
export async function getBysConfigApi() {
    return await request.get('/api/v1/env')
}

// 所有标签
export async function getAllLabelsApi() {
    return await request.get('/api/v1/tag')
}

// 获取首页展示的标签列表
export async function getHomeLabelApi() {
    return await request.get('/api/v1/tag/home')
}

// 更新首页展示的标签列表
export async function updateHomeLabelApi(tag_ids) {
    return await request.post('/api/v1/tag/home', {
        tag_ids
    })
}

/**
 * 技能 工作流详情
 */
export async function getFlowApi(flowId: string, version: string = 'v1', shareToken?: string): Promise<any> {
    const headers = shareToken ? { 'share-token': shareToken } : {}

    return await request.get(`/api/${version}/flows/${flowId}`, { headers })
}

/**
 * 删除的技能 工作流详情
 */
export async function getDeleteFlowApi(chatId: string): Promise<any> {
    return await request.get(`/api/v1/chat/info?chat_id=${chatId}`).then(res => {
        res.data.name = res.data.flow_name
        return res
    })
}

// 获取助手详情
export const getAssistantDetailApi = async (id: string, shareToken?: string): Promise<any> => {
    const headers = shareToken ? { 'share-token': shareToken } : {}

    return await request.get(`/api/v1/assistant/info/${id}`, {
        headers
    })
};

export const baseMsgItem = {
    id: Math.random() * 1000000,
    isSend: false,
    message: '',
    chatKey: '',
    thought: '',
    category: '',
    files: [],
    end: true,
    user_name: '',
    create_time: "",
    update_time: ""
}

/**
 * 赞 踩消息
 */
export const likeChatApi = (msgId, liked) => {
    liked && trackingApi({ message_id: msgId, operation_type: liked === 1 ? 'like' : 'dislike' });
    return request.post(`/api/v1/liked`, { message_id: msgId, liked });
};

/**
 * 点击复制上报
 * */
export const copyTrackingApi = (msgId) => {
    trackingApi({ message_id: msgId, operation_type: 'copy' });
    return request.post(`/api/v1/chat/copied`, { message_id: msgId });
}

/**
 * 踩消息反馈
 */
export const disLikeCommentApi = (message_id, comment) => {
    return request.post(`/api/v1/chat/comment`, { message_id, comment });
};

/**
 * Tracking
 */
export const trackingApi = (data: { message_id: string, operation_type: 'dislike' | 'like' | 'copy' }) => {
    return request.post(`/api/v1/session/chat/message/telemetry`, data);
}

/**
 * 技能 工作流详情
 */
export async function getChatHistoryApi({ flowId, chatId, flowType, id, shareToken }
    : { flowId: string, chatId: string, flowType: string, id?: number, shareToken?: string }): Promise<any> {
    const filterFlowMsg = (data) => {
        return data.filter(item =>
            ["question", "output_with_input_msg", "output_with_choose_msg", "stream_msg", "output_msg", "guide_question", "guide_word", "node_run", "answer"].includes(item.category)
            && (item.message || item.reasoning_log))
    }

    const filterSkillMsg = (data) => {
        return data.filter(item =>
            ['answer', 'question', 'processing', 'system', 'report', 'tool', 'knowledge', 'divider', 'flow', 'reasoning_answer'].includes(item.category)
        )
    }

    const headers = shareToken ? { 'share-token': shareToken } : {}

    return await request.get(`/api/v1/chat/history?flow_id=${flowId}&chat_id=${chatId}&page_size=40&id=${id || ''}`, {
        headers
    }).then(res => {
        if (res.status_code !== 200) return []
        const newData = Number(flowType) === 10 ? filterFlowMsg(res.data) : filterSkillMsg(res.data)

        return newData.map(item => {
            let { message, files, is_bot, isSend, intermediate_steps, category, ...other } = item
            try {
                message = message && message[0] === '{' ? JSON.parse(message) : message || ''
            } catch (e) {
                // 未考虑的情况暂不处理
                console.error('消息 to JSON error :>> ', e);
            }
            // 修正数据
            const _isSend = isSend || !is_bot;
            const _category = _isSend ? 'question' : category
            const _files = (files ? JSON.parse(files) : []).map(file => {
                return {
                    file_name: file.file_name || file.name,
                    file_url: file.file_url || file.path,
                }
            })

            let chatKey = Number(flowType) === 5 ? 'input' : (typeof message === 'string' ? undefined : Object.keys(message)[0]);
            chatKey = chatKey === 'data' ? 'query' : chatKey // 排除data

            return {
                ...other,
                category: _category,
                chatKey,
                end: true,
                files: _files,
                isSend: _isSend,
                message,
                thought: intermediate_steps,
                reasoning_log: message.reasoning_content || '',
                noAccess: true
            }
        })
    });
}


// 溯源-分词
export async function splitWordApi(word: string, messageId: string): Promise<string[]> {
    return await request.get(`/api/v1/qa/keyword?message_id=${messageId}`)
    // .then(res => {
    //     return {data: null, status_code: 14001, message: "请求参数错误"}
    // })
}

// 溯源-获取 chunks
export async function getSourceChunksApi(chatId: string, messageId: number, keys: string) {
    try {
        const res: any[] = await request.post(`/api/v1/qa/chunk`, {
            chat_id: chatId,
            message_id: messageId,
            keys,
        })
        const fileMap = {}
        const chunks = res.data
        chunks.forEach(chunk => {
            const list = fileMap[chunk.file_id]
            if (list) {
                fileMap[chunk.file_id].push(chunk)
            } else {
                fileMap[chunk.file_id] = [chunk]
            }
        });

        return Object.keys(fileMap).map(fileId => {
            const { file_id: id, source: fileName, source_url, original_url: originUrl, ...other } = fileMap[fileId][0]

            const chunks = fileMap[fileId].sort((a, b) => b.score - a.score)
                .map(chunk => ({
                    box: chunk.chunk_bboxes,
                    score: chunk.score
                }))
            const score = chunks[0].score

            // 兼容后端历史逻辑
            let fileUrl = ''
            let suffix = fileName.split('.').pop().toLowerCase()
            let isNew = false
            if (['uns', 'local'].includes(other.parse_type)) {
                fileUrl = other.chunk_bboxes ? source_url : originUrl;
                if (other.chunk_bboxes) {
                    suffix = 'pdf'
                }
            } else if (['etl4lm', 'un_etl4lm'].includes(other.parse_type)) {
                fileUrl = source_url || originUrl
                isNew = true
            }
            return { id, fileName, suffix, isNew, fileUrl, originUrl, chunks, ...other, score }
        }).sort((a, b) => b.score - a.score)
    } catch (error) {
        console.error(error);
        throw error;
    }
}


/**
 * 聊天窗上传文件
 */
export async function uploadChatFile(v, file: File, onProgress): Promise<any> {
    const formData = new FormData();
    formData.append("file", file);
    return await request.post(`/api/v1/knowledge/upload`, formData, {
        headers: {
            "Content-Type": "multipart/form-data"
        },
        onUploadProgress: (progressEvent) => {
            // Calculate progress percentage
            if (progressEvent.total) {
                const progress = Math.round((progressEvent.loaded * 100) / progressEvent.total);
                onProgress(progress);
            }
        }
    });
}


export async function postBuildInit(data: {
    flow: any
    chatId?: string
    versionId?: number
}): Promise<any> {
    const { flow, chatId, versionId } = data;
    const qstr = versionId ? `?version_id=${versionId}` : ''
    return await request.post(`/api/v1/build/init/${flow.id}${qstr}`, chatId ? { chat_id: chatId } : flow);
}

/**
 * 上传文件
 */
export async function uploadLibFile(data, config, type: 'knowledge' | 'icon', url) {
    const urls = {
        knowledge: '/api/v1/knowledge/upload',
        icon: '/api/v1/upload/icon',
    }
    return await request.post(url || urls[type], data, config);
}
export async function uploadFile(
    file: File,
    id: string
): Promise<any> {
    const formData = new FormData();
    formData.append("file", file);
    return await request.post(`/api/v1/upload/${id}`, formData);
}

// Function to upload the file with progress tracking
export const uploadFileWithProgress = async (file, callback, type: 'knowledge' | 'icon' = 'knowledge', url): Promise<any> => {
    try {
        const formData = new FormData();
        formData.append('file', file);

        const config = {
            headers: { 'Content-Type': 'multipart/form-data;charset=utf-8' },
            onUploadProgress: (progressEvent) => {
                const { loaded, total } = progressEvent;
                const progress = Math.round((loaded * 100) / total);
                console.log(`Upload progress: ${file.name} ${progress}%`);
                callback(progress)
                // You can update your UI with the progress information here
            },
        };

        // Convert the FormData to binary using the FileReader API
        const data = await uploadLibFile(formData, config, type, url);

        data && callback(100);

        console.log('Upload complete:', data);
        return data.data
        // Handle the response data as needed
    } catch (error) {
        console.error('Error uploading file:', error);
        return ''
        // Handle errors
    }
};


/**
 * get组件 variables 变量
 * params flow_id, node_id
 */
const enum VariableType {
    /** 文本 */
    Text = "text",
    /** 下拉框 */
    Select = "select",
    /** 文件 */
    File = "file"
}
export function getVariablesApi(params) {
    return (request.get(`/api/v1/variable/list`, { params }) as Promise<any[]>).then(res => {
        return res.data.map((item) => {
            const types = ['', VariableType.Text, VariableType.Select, VariableType.File]
            return {
                id: item.id,
                update: true,
                name: item.variable_name,
                type: types[item.value_type],
                nodeId: item.node_id,
                required: item.is_option === 1,
                maxLength: item.value_type === 1 ? item.value : '',
                options: item.value_type === 2 ? item.value
                    .split(',')
                    .map((op, i) => ({ key: i, value: op })) : [],
                value: ''
            }
        }) as any[]
    });
}
export async function getFrequently(page, limit) {
    return await request.get('/api/v1/workstation/app/frequently_used', {
        params: {
            page,
            limit
        }
    })
}

export async function addToFrequentlyUsed(user_link_type, type_detail) {
    return await request.post('/api/v1/workstation/app/frequently_used', {
        user_link_type, type_detail
    }, { showError: true });
}

// 从常用列表移除
export async function removeFromFrequentlyUsed(user_id, type, type_detail) {

    const url = `/api/v1/workstation/app/frequently_used?user_id=${user_id}&user_link_type=${type}&type_detail=${type_detail}`;
    return await request.delete(url);
}
export async function getUncategorized(page: number = 1, pageSize: number = 8) {
    return await request.get('/api/v1/workstation/app/uncategorized', {
        params: {
            page,
            limit: pageSize
        }
    })
}

export async function getAppsApi({ page = 1, pageSize = 8, keyword, tag_id = -1, type }) {
    const tagIdStr = tag_id === -1 ? '' : `&tag_id=${tag_id}`
    const map = { assistant: 5, skill: 1, flow: 10 }
    const flowType = map[type] ? `&flow_type=${map[type]}` : ''
    const { data, total }: { data: any[], total: number } = await request.get(`/api/v1/workflow/list?page_num=${page}&page_size=${pageSize}&name=${keyword}${tagIdStr}${flowType}`);
    const newData = data.data.map(item => {
        if (item.flow_type !== 5) return item
        return {
            ...item,
            version_list: item.version_list || [],
        }
    })
    return { data: newData, total };
}


export const getChatOnlineApi = async (page, keyword, tag_id, disableLimit = 8) => {
    const params = {
        page,
        keyword,
        limit: disableLimit
    }
    if (tag_id !== -1 && tag_id != null) {
        params.tag_id = tag_id
    }

    return await request.get(`/api/v1/chat/online`, { params })
}
