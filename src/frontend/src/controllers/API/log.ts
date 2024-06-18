import axios from "../request";

// 分页获取审计列表
export async function getLogsApi({page, pageSize, userIds, groupId, start, end, moduleId, actionId}:{
    page:number,
    pageSize:number,
    userIds?:any[],
    groupId?:number,
    start?:string,
    end?:string,
    moduleId?:number,
    actionId?:number
}):Promise<{data:any[], total:number}> {
    return {
        data: [
            {id:1,name:'test1'},
            {id:1,name:'test1'},
            {id:1,name:'test1'},
            {id:1,name:'test1'},
        ],
        total:4
    }
}
// 系统模块
export async function getModulesApi():Promise<[]> {
    return (await axios.get('')).data
}
// 全部操作行为
export const getActionsApi = async () => {

}
// 系统模块下操作行为
export const getActionsByModuleApi = async (moduleId) => {

}