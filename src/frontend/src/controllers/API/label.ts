import axios from "../request";

export async function getAllLabelsApi() {
    return await axios.get('/api/v1/tag')
}

// admin全局创建一个标签
export async function createLabelApi(name:string) {
    return await axios.post('/api/v1/tag', {
        name
    })
}

// admin修改标签
export async function updateLabelApi(id:number, name:string) {
    return await axios.put('/api/v1/tag', {
        tag_id: id,
        name
    })
}

// admin删除标签
export async function deleteLabelApi(id:number) {
    return await axios.delete('/api/v1/tag', {
        data: {
            tag_id: id
        }
    })
}

// 建立助手或技能和标签的关系，即选择标签
export async function createLinkApi(tag_id:number, resource_id:string, resource_type:number) {
    return await axios.post('/api/v1/tag/link', {
        tag_id,
        resource_id,
        resource_type
    })
}

// 删除助手或技能和标签的关系，即不选标签
export async function deleteLinkApi(tag_id:number, resource_id:string, resource_type:number) {
    return await axios.delete('/api/v1/tag/link', {
        data: {
            tag_id,
            resource_id,
            resource_type
        }
    })
}

// 获取首页展示的标签列表
export async function getHomeLabelApi() {
    return await axios.get('/api/v1/tag/home')
}

// 更新首页展示的标签列表
export async function updateHomeLabelApi(tag_ids) {
    return await axios.post('/api/v1/tag/home', {
        tag_ids
    })
}