import request from "./request";

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