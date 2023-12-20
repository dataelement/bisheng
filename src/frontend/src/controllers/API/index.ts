import axios, { AxiosResponse } from "axios";
import { ReactFlowJsonObject } from "reactflow";
import { APIObjectType, sendAllProps } from "../../types/api/index";
import { FlowStyleType, FlowType } from "../../types/flow";
import {
  APIClassType,
  BuildStatusTypeAPI,
  InitTypeAPI,
  PromptTypeAPI,
  UploadFileTypeAPI,
  errorsTypeAPI,
} from "./../../types/api/index";


axios.interceptors.response.use(function (response) {
  if (response.data.status_code && response.data.status_code!==200) {
    return Promise.reject({
      response: {
        data: { detail: response.data.status_message }
      }
    });
  }
  return response;
}, function (error) {
  if (error.response.status === 401) {
    // cookie expires
    console.error('登录过期 :>> ');
    const infoStr = localStorage.getItem('UUR_INFO')
    localStorage.removeItem('UUR_INFO')
    infoStr && location.reload()
  }
  return Promise.reject(error);
})

export default axios
/**
 * Fetches all objects from the API endpoint.
 *
 * @returns {Promise<AxiosResponse<APIObjectType>>} A promise that resolves to an AxiosResponse containing all the objects.
 */
export async function getAll(): Promise<AxiosResponse<APIObjectType>> {
  return await axios.get(`/api/v1/all`);
}

const GITHUB_API_URL = "https://api.github.com";

export async function getRepoStars(owner, repo) {
  try {
    const response = await axios.get(
      `${GITHUB_API_URL}/repos/${owner}/${repo}`
    );
    return response.data.stargazers_count;
  } catch (error) {
    console.error("Error fetching repository data:", error);
    return null;
  }
}

/**
 * 修改配置
 */
export async function getAppConfig() {
  return await axios.get(`/api/v1/env`);
}

/**
 * Reads all templates from the database.
 *
 * @returns {Promise<any>} The flows data.
 * @throws Will throw an error if reading fails.
 */
export async function readTempsDatabase() {
  try {
    const response = await axios.get("/api/v1/skill/template/");
    if (response.status !== 200) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    return response.data;
  } catch (error) {
    console.error(error);
    throw error;
  }
}
/**
 * 创建模板.
 *
 * @param data {flow_id name description}
 * @returns  null.
 */
export function createTempApi(params) {
  return axios.post(`/api/v1/skill/template/create`, params);
}
/**
 * 删除模板.
 *
 * @param data {flow_id name description}
 * @returns  null.
 */
export function deleteTempApi(temp_id) {
  return axios.delete(`/api/v1/skill/template/${temp_id}`);
}
/**
 * 修改模板.
 *
 * @param data {flow_id name description}
 * @returns  null.
 */
export function updateTempApi(temp_id, data) {
  return axios.post(`/api/v1/skill/template/${temp_id}`, data);
}

/**
 * 获取知识库列表
 *
 */
export async function readFileLibDatabase(page = 1, pageSize = 40) {
  try {
    const response = await axios.get(`/api/v1/knowledge/?page_num=${page}&page_size=${pageSize}`);
    if (response.status !== 200) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    const { data, total } = response.data
    return { data, pages: Math.ceil(total / pageSize) };
  } catch (error) {
    console.error(error);
    throw error;
  }
}
/**
 * 获取知识库下文件列表
 *
 */
export async function readFileByLibDatabase(id, page) {
  const pageSize = 20
  const response = await axios.get(`/api/v1/knowledge/file_list/${id}?page_size=${pageSize}&page_num=${page}`);
  const { data, total, writeable } = response.data
  return { data, writeable, pages: Math.ceil(total / pageSize) }
}

/**
 * 上传文件
 */
export async function uploadLibFile(data, config) {
  return await axios.post(`/api/v1/knowledge/upload`, data, config);
}

/**
 * 确定上传文件
 * file_path knowledge_id chunck_size
 */
export async function subUploadLibFile(data) {
  return await axios.post(`/api/v1/knowledge/process`, data);
}

/**
 * 创建支持库
 *
 */
export async function createFileLib(data) {
  return await axios.post(`/api/v1/knowledge/create`, data);
}

/**
 * 删除支持库
 *
 */
export async function deleteFileLib(id) {
  return await axios.delete(`/api/v1/knowledge/${id}`);
}

/**
 * 删除知识库下文件
 *
 */
export async function deleteFile(id) {
  return await axios.delete(`/api/v1/knowledge/file/${id}`);
}

/**
 * 获取模型列表
 */
export async function getEmbeddingModel() {
  return await axios.get(`/api/v1/knowledge/embedding_param`);
}

/**
 * 获取RT服务列表
 */
export async function getServicesApi() {
  return await axios.get(`/api/v1/server/list_server`);
}
/**
 * 获取RT服务列表
 */
export async function addServiceApi(name: string, url: string) {
  return await axios.post(`/api/v1/server/add`,
    { endpoint: url, server: name, remark: 'RT模块创建' });
}
/**
 * 删除知识库下文件
 *
 */
export async function deleteServiceApi(id) {
  return await axios.delete(`/api/v1/server/${id}`);
}

/**
 * Sends data to the API for prediction.
 *
 * @param {sendAllProps} data - The data to be sent to the API.
 * @returns {AxiosResponse<any>} The API response.
 */
export async function sendAll(data: sendAllProps) {
  return await axios.post(`/api/v1/predict`, data);
}

export async function postValidateCode(
  code: string
): Promise<AxiosResponse<errorsTypeAPI>> {
  return await axios.post("/api/v1/validate/code", { code });
}

/**
 * Checks the prompt for the code block by sending it to an API endpoint.
 * @param {string} name - The name of the field to check.
 * @param {string} template - The template string of the prompt to check.
 * @param {APIClassType} frontend_node - The frontend node to check.
 * @returns {Promise<AxiosResponse<PromptTypeAPI>>} A promise that resolves to an AxiosResponse containing the validation results.
 */
export async function postValidatePrompt(
  name: string,
  template: string,
  frontend_node: APIClassType
): Promise<AxiosResponse<PromptTypeAPI>> {
  return await axios.post("/api/v1/validate/prompt", {
    name: name,
    template: template,
    frontend_node: frontend_node,
  });
}

/**
 * Fetches a list of JSON files from a GitHub repository and returns their contents as an array of FlowType objects.
 *
 * @returns {Promise<FlowType[]>} A promise that resolves to an array of FlowType objects.
 */
export async function getExamples(): Promise<FlowType[]> {
  return Promise.resolve([])
}

/**
 * Saves a new flow to the database.
 *
 * @param {FlowType} newFlow - The flow data to save.
 * @returns {Promise<any>} The saved flow data.
 * @throws Will throw an error if saving fails.
 */
export async function saveFlowToDatabase(newFlow: {
  name: string;
  id: string;
  data: ReactFlowJsonObject;
  description: string;
  style?: FlowStyleType;
}): Promise<FlowType> {
  try {
    const id = newFlow.id ? { flow_id: newFlow.id } : {}
    const response = await axios.post("/api/v1/flows/", {
      ...id,
      name: newFlow.name,
      data: newFlow.data,
      description: newFlow.description,
    });
    if (response.status !== 201) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    return response.data;
  } catch (error) {
    console.error(error);
    throw error;
  }
}
/**
 * Updates an existing flow in the database.
 *
 * @param {FlowType} updatedFlow - The updated flow data.
 * @returns {Promise<any>} The updated flow data.
 * @throws Will throw an error if the update fails.
 */
export async function updateFlowInDatabase(
  updatedFlow: FlowType
): Promise<FlowType> {
  try {
    const response = await axios.patch(`/api/v1/flows/${updatedFlow.id}`, {
      name: updatedFlow.name,
      data: updatedFlow.data,
      description: updatedFlow.description,
    });

    if (response.status !== 200) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    return response.data;
  } catch (error) {
    console.error(error);
    throw error;
  }
}

/**
 * 上下线
 *
 */
export async function updataOnlineState(id, updatedFlow, open) {
  try {
    const response = await axios.patch(`/api/v1/flows/${id}`, {
      name: updatedFlow.name,
      description: updatedFlow.description,
      status: open ? 2 : 1
    });

    if (response.status !== 200) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    return response.data;
  } catch (error) {
    console.error(error);
    throw error;
  }
}

/**
 * Reads all flows from the database.
 *
 * @returns {Promise<any>} The flows data.
 * @throws Will throw an error if reading fails.
 */
export async function readFlowsFromDatabase(page: number = 1, search: string) {
  try {
    const response = await axios.get(`/api/v1/flows/?page_num=${page}&page_size=${20}&name=${search}`);
    if (response.status !== 200) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    const { data, total } = response.data
    return { data, pages: Math.ceil(total / 20) };
  } catch (error) {
    console.error(error);
    throw error;
  }
}
/**
 * 获取在线技能列表.
 *
 * @returns {Promise<any>}.
 * @throws .
 */
export async function readOnlineFlows(page: number = 1) {
  try {
    const response = await axios.get(`/api/v1/flows/?page_num=${page}&page_size=${100}&status=2`);
    if (response.status !== 200) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    const { data, total } = response.data
    return data;
  } catch (error) {
    console.error(error);
    throw error;
  }
}

export async function downloadFlowsFromDatabase() {
  try {
    const response = await axios.get("/api/v1/flows/download/");
    if (response.status !== 200) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    return response.data;
  } catch (error) {
    console.error(error);
    throw error;
  }
}

export async function uploadFlowsToDatabase(flows) {
  try {
    const response = await axios.post(`/api/v1/flows/upload/`, flows);

    if (response.status !== 201) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    return response.data;
  } catch (error) {
    console.error(error);
    throw error;
  }
}

/**
 * Deletes a flow from the database.
 *
 * @param {string} flowId - The ID of the flow to delete.
 * @returns {Promise<any>} The deleted flow data.
 * @throws Will throw an error if deletion fails.
 */
export async function deleteFlowFromDatabase(flowId: string) {
  try {
    const response = await axios.delete(`/api/v1/flows/${flowId}`);
    if (response.status !== 200) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    return response.data;
  } catch (error) {
    console.error(error);
    throw error;
  }
}

/**
 * 获取会话列表
 */
export const getChatsApi = () => {
  return axios.get(`/api/v1/chat/list`).then(res =>
    res.data?.filter(el => el.chat_id) || []
  )
};

/**
 * 获取会话列表
 */
export const deleteChatApi = (chatId) => {
  return axios.delete(`/api/v1/chat/${chatId}`)
};


/**
 * 获取会话消息记录
 *
 * @param id flow_id chat_id - .
 * @returns {Promise<any>} his data.
 */
export async function getChatHistory(flowId: string, chatId: string, pageSize: number, id?: number) {
  try {
    const response = await axios.get(`/api/v1/chat/history?flow_id=${flowId}&chat_id=${chatId}&page_size=${pageSize}&id=${id || ''}`);
    if (response.status !== 200) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    return response.data;
  } catch (error) {
    console.error(error);
    return [];
  }
}

/**
 * 赞 踩消息
 */
export const likeChatApi = (chatId, liked) => {
  return axios.post(`/api/v1/liked`, { message_id: chatId, liked });
};


/**
 * Fetches a flow from the database by ID.
 *
 * @param {number} flowId - The ID of the flow to fetch.
 * @returns {Promise<any>} The flow data.
 * @throws Will throw an error if fetching fails.
 */
export async function getFlowFromDatabase(flowId: string) {
  try {
    const response = await axios.get(`/api/v1/flows/${flowId}`);
    if (response.status !== 200) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    return response.data;
  } catch (error) {
    console.error(error);
    return null
  }
}

/**
 * Fetches flow styles from the database.
 *
 * @returns {Promise<any>} The flow styles data.
 * @throws Will throw an error if fetching fails.
 */
export async function getFlowStylesFromDatabase() {
  try {
    const response = await axios.get("/api/v1/flow_styles/");
    if (response.status !== 200) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    return response.data;
  } catch (error) {
    console.error(error);
    throw error;
  }
}

/**
 * Saves a new flow style to the database.
 *
 * @param {FlowStyleType} flowStyle - The flow style data to save.
 * @returns {Promise<any>} The saved flow style data.
 * @throws Will throw an error if saving fails.
 */
export async function saveFlowStyleToDatabase(flowStyle: FlowStyleType) {
  try {
    const response = await axios.post("/api/v1/flow_styles/", flowStyle, {
      headers: {
        accept: "application/json",
        "Content-Type": "application/json",
      },
    });

    if (response.status !== 201) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    return response.data;
  } catch (error) {
    console.error(error);
    throw error;
  }
}

/**
 * Fetches the version of the API.
 *
 * @returns {Promise<AxiosResponse<any>>} A promise that resolves to an AxiosResponse containing the version information.
 */
export async function getVersion() {
  const respnose = await axios.get("/api/v1/version");
  return respnose.data;
}

/**
 * Fetches the health status of the API.
 *
 * @returns {Promise<AxiosResponse<any>>} A promise that resolves to an AxiosResponse containing the health status.
 */
export async function getHealth() {
  return await axios.get("/health"); // Health is the only endpoint that doesn't require /api/v1
}

/**
 * Fetches the build status of a flow.
 * @param {string} flowId - The ID of the flow to fetch the build status for.
 * @returns {Promise<BuildStatusTypeAPI>} A promise that resolves to an AxiosResponse containing the build status.
 *
 */
export async function getBuildStatus(
  flowId: string
): Promise<BuildStatusTypeAPI> {
  return await axios.get(`/api/v1/build/${flowId}/status`);
}

//docs for postbuildinit
/**
 * Posts the build init of a flow.
 * @param {string} flowId - The ID of the flow to fetch the build status for.
 * @returns {Promise<InitTypeAPI>} A promise that resolves to an AxiosResponse containing the build status.
 *
 */
export async function postBuildInit(
  flow: FlowType,
  chatId: string
): Promise<AxiosResponse<InitTypeAPI>> {
  return await axios.post(`/api/v1/build/init/${flow.id}`, { ...flow, chat_id: chatId });
}

// fetch(`/upload/${id}`, {
//   method: "POST",
//   body: formData,
// });
/**
 * Uploads a file to the server.
 * @param {File} file - The file to upload.
 * @param {string} id - The ID of the flow to upload the file to.
 */
export async function uploadFile(
  file: File,
  id: string
): Promise<AxiosResponse<UploadFileTypeAPI>> {
  const formData = new FormData();
  formData.append("file", file);
  return await axios.post(`/api/v1/upload/${id}`, formData);
}

/**
 * ************************ model
 */

/**
 * 获取知识库下文件列表
 *
 */
export async function serverListApi() {
  const response = await axios.get(`/api/v1/server/list`);
  return response.data
}

/**
 * 上下线
 */
export async function switchOnLineApi(id, on) {
  return await axios.post(`/api/v1/server/${on ? 'load' : 'unload'}`, { deploy_id: id });
}

/**
 * 修改配置
 */
export async function updateConfigApi(id, config) {
  return await axios.post(`/api/v1/server/update`, { id, config });
}

/**
 * 获取gpu
 *
 */
export async function GPUlistApi() {
  const response = await axios.get(`/api/v1/server/GPU`);
  return response.data
}

/**
 * ************************ 溯源
 */
// 分词
export async function splitWordApi(word: string, messageId: string) {
  return await axios.get(`/api/v1/qa/keyword?answer=${'https://github.com/dataelement/bishe&ng/blob/v0.1.9.5/src/frontend/src/controllers/API/index.ts'}&message_id=${messageId}`)
}

// 获取 chunks
export async function getSourceChunksApi(chatId: string, messageId: number, keys: string) {
  try {
    const response = await axios.get(`/api/v1/qa/chunk?chat_id=${chatId}&message_id=${messageId}&keys=${keys}`)
    if (response.status !== 200) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    const fileMap = {}
    const chunks = response.data.data
    chunks.forEach(chunk => {
      const list = fileMap[chunk.file_id]
      if (list) {
        fileMap[chunk.file_id].push(chunk)
      } else {
        fileMap[chunk.file_id] = [chunk]
      }
    });

    return Object.keys(fileMap).map(fileId => {
      const { file_id: id, source: fileName, source_url: fileUrl, original_url: originUrl, ...other } = fileMap[fileId][0]

      const chunks = fileMap[fileId].sort((a, b) => b.score - a.score)
        .map(chunk => ({
          box: chunk.chunk_bboxes,
          score: chunk.score
        }))
      const score = chunks[0].score

      return { id, fileName, fileUrl, originUrl, chunks, score, ...other }
    }).sort((a, b) => b.score - a.score)
  } catch (error) {
    console.error(error);
    throw error;
  }
}

/**
 * 
 * @param { object } options  - 参数对象
 * @param { string } options.chatId  - 会话 id
 * @param { number } options.solved  状态    0 初始值， 1  解决, 2 未解决
 * @returns 
 */
export async function chatResolved(options) {
  const { chatId, solved = 0 } = options || {}
  return axios.post('/api/v2/chat/solved', {
      chat_id:chatId,
      solved
  })
}