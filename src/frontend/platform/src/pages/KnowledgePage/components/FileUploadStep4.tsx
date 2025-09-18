import CardComponent from "@/components/bs-comp/cardComponent";
import ProgressItem from "@/components/bs-comp/knowledgeUploadComponent/ProgressItem";
import { Button } from "@/components/bs-ui/button";
import { generateUUID } from "@/components/bs-ui/utils";
import { readFileByLibDatabase } from "@/controllers/API";
import { getLlmDefaultModel } from "@/controllers/API/finetune";
import { createWorkflowApi, getWorkflowNodeTemplate } from "@/controllers/API/workflow";
import { useKnowledgeDetails } from "@/controllers/hooks/knowledge";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

export default function FileUploadStep4({ data ,kId}) {
    const [finish, setFinish] = useState(true)
    const navigate = useNavigate()
    const { id: kid } = useParams()
    console.log(data,kId,44);

    const [files, setFiles] = useState([])
    const timerRef = useRef(null); // 轮询定时器引用
    const fileIdsRef = useRef([]); // 文件ID列表引用
    const processingRef = useRef(new Set()); // 跟踪正在处理的文件ID
    const isPollingRef = useRef(false); // 防止轮询并发
    const hasInitialized = useRef(false); 

    // 初始化文件状态（只执行一次）
useEffect(() => {
    if (data.length > 0 && !hasInitialized.current) { 
        console.log(data, 111);
        
        const initialFiles = data.map(item => ({
            id: item.id || item.fileId, // 前端文件唯一标识
            fileName: item.fileName,
            error: false,
            reason: '',
            progress: 'await'
        }));
        console.log(initialFiles, 45);
        
        setFiles(initialFiles);
        
        // 关键：fileIdsRef 和 processingRef 都存前端文件的id（确保数据一致）
        const frontEndFileIds = initialFiles.map(file => file.id);
        fileIdsRef.current = frontEndFileIds; 
        processingRef.current.clear();
        frontEndFileIds.forEach(id => processingRef.current.add(id)); // 用同一批ID
        
        setFinish(false);
        hasInitialized.current = true;
    }
}, [data]);


    // 轮询文件状态
 // 轮询文件状态（完整修复版）
useEffect(() => {
    // 1. 先定义轮询函数（必须先定义再调用，修复“未定义就调用”问题）
    const pollFilesStatus = async () => {
        if (isPollingRef.current) return;
        isPollingRef.current = true;

       try {
        // 修复待处理文件ID异常（之前为[0]，实际应取前端文件ID）
        const pendingFileIds = Array.from(processingRef.current);
        console.log("正确待处理文件ID:", pendingFileIds); // 现在应为['fe9d1b', 'd3b66c', ...]
        
        // 接口参数保持不变（后端可能用knowledge_id过滤，file_ids可传前端ID或留空）
        const res = await readFileByLibDatabase({
            id: kid || kId,
            page: 0,
            pageSize: 0,
            file_ids: pendingFileIds 
        });

// 轮询函数中setFiles的状态更新逻辑（增加清理后日志）
setFiles(prev => {
    const updatedFiles = [...prev];
    const resMap = new Map(res.data.map(item => [item.file_name.toLowerCase().trim(), item])); // 用文件名建Map，匹配更快
    
    updatedFiles.forEach((file, index) => {
        const resItem = resMap.get(file.fileName.toLowerCase().trim());
        if (resItem && resItem.status === 2) {
            // 双重确认：从processingRef移除当前文件id
            if (processingRef.current.has(file.id)) {
                processingRef.current.delete(file.id);
                console.log(`移除待处理ID: ${file.id}，剩余待处理: ${processingRef.current.size}`);
            }
            updatedFiles[index] = { ...file, progress: 'end' };
        } else if (resItem && resItem.status === 3) {
            if (processingRef.current.has(file.id)) {
                processingRef.current.delete(file.id);
                console.log(`移除待处理ID: ${file.id}（失败），剩余待处理: ${processingRef.current.size}`);
            }
            updatedFiles[index] = { ...file, progress: 'end', error: true, reason: resItem.remark || '解析失败' };
        }
    });

    return updatedFiles;
});

        } catch (e) {
            console.error("轮询出错:", e);
        } finally {
            isPollingRef.current = false;
        }
    };

    // 3. 处理“无文件”的情况（此时才调用已定义的 pollFilesStatus）
    if (fileIdsRef.current.length === 0) {
        const timer = setTimeout(() => {
            if (fileIdsRef.current.length > 0) {
                pollFilesStatus(); // 此时函数已定义，可正常调用
            }
        }, 100);
        return () => clearTimeout(timer);
    }

    // 4. 有文件时，立即轮询 + 定时轮询
    if (fileIdsRef.current.length > 0) {
        pollFilesStatus(); // 立即执行第一次
        timerRef.current = setInterval(pollFilesStatus, 5000);
    } else {
        setFinish(true);
    }

    // 5. 清理定时器
    return () => {
        if (timerRef.current) clearInterval(timerRef.current);
    };
}, [kid, kId]); // 只依赖路由参数
useEffect(() => {
    return () => {
        hasInitialized.current = false;
    };
}, []);
    // 检查所有文件是否完成
    useEffect(() => {
        // 当处理中集合为空时，标记为完成
        if (processingRef.current.size === 0 && fileIdsRef.current.length > 0) {
            console.log('所有文件处理完成');
            if (timerRef.current) {
                clearInterval(timerRef.current);
            }
            setFinish(true);
        } else {
            setFinish(false);
        }
    }, [files]); // 依赖文件状态变化

    console.log('files :>> ', files);
    
    let finalId = kid;
    if (kId) {
        finalId = kId.replace(/\D/g, '');
    }
    console.log(finalId,333);
    
    const [details] = useKnowledgeDetails([finalId])
    
    const handleCreateFlow = async (params) => {
        const model = await getLlmDefaultModel()
        console.log(details,9999);
        
        const flow = await getKnowledgeDefaultFlowTemplate(finalId, details[0]?.name || '', model.model_id)
        const res = await captureAndAlertRequestErrorHoc(createWorkflowApi(
            "文档知识库问答-" + generateUUID(5),
            "检索文档知识库，根据检索结果进行回答。",
            "",
            flow))
        if (res) navigate('/flow/' + res.id)
    }

    return <div className={`max-w-[1400px] mx-auto px-20 pt-4 relative`}>
        <div className="flex gap-4">
            <div className="flex-1">
                <h1 className="text-3xl text-primary mt-2">{finish ? '文档数据解析已完成' : '文档数据正在准备中'}</h1>
                <p className="text-base text-gray-500 mt-2">您可以返回知识库文件列表查看解析状态</p>
                <div className="overflow-y-auto mt-4 space-y-2 pb-10 max-h-[calc(100vh-400px)]">
                    {files.map(item => <ProgressItem analysis key={item.id} item={item} />)}
                </div>
                <div className="flex justify-end gap-4">
                    <Button onClick={() => navigate(-1)}>返回知识库</Button>
                </div>
            </div>
            {finish && <div className="w-96 pt-24">
                <CardComponent
                    data={null}
                    type='assist'
                    title="构建知识库问答智能体"
                    description={(<p><p>文档解析完成后。使用预制的知识库问答模版建立智能体，并测试问答效果</p></p>)}
                    onClick={handleCreateFlow}
                ></CardComponent>
            </div>}
        </div>
    </div>
};

// 保持getKnowledgeDefaultFlowTemplate函数不变
const getKnowledgeDefaultFlowTemplate = async (kid, kname, modelId) => {
    const templates = await getWorkflowNodeTemplate()
    let startNode = null
    let inputNode = null
    let ragNode = null

    templates.forEach(node => {
        const nodeCopy = JSON.parse(JSON.stringify(node)); // 深拷贝节点

        if (node.type === 'start') {
            nodeCopy.id = `start_${generateUUID(5)}`;
            startNode = nodeCopy;
        } else if (node.type === 'input') {
            nodeCopy.id = `input_${generateUUID(5)}`;
            inputNode = nodeCopy;
        } else if (node.type === 'rag') {
            nodeCopy.id = `rag_${generateUUID(5)}`;
            ragNode = nodeCopy;
        }
    });

    ragNode.group_params.forEach(group => {
        group.params.forEach(param => {
            if (param.key === 'user_question') {
                param.value = [inputNode.id + ".user_input"];
                param.varZh = {
                    [inputNode.id + ".user_input"]: "输入/user_input"
                };
            } else if (param.key === 'knowledge') {
                param.value.value = [
                    {
                        "key": Number(kid),
                        "label": kname
                    }
                ];
            } else if (param.key === 'user_prompt') {
                param.value = `用户问题：{{#${ragNode.id}.user_question#}}\n参考文本：{{#${ragNode.id}.retrieved_result#}}\n你的回答：`;
                param.varZh = {
                    [`${ragNode.id}.user_question`]: "user_question",
                    [`${ragNode.id}.retrieved_result`]: "retrieved_result"
                };
            } else if (param.key === 'model_id') {
                param.value = modelId
            } else if (param.key === 'output_user_input') {
                param.value = [
                    {
                        "key": "output_user_input",
                        "label": "output_user_input"
                    }
                ]
            }
        });
    })

    return {
        data: {
            "edges": [
                {
                    "id": `xy-edge__${startNode.id}right_handle-${inputNode.id}left_handle`,
                    "type": "customEdge",
                    "source": startNode.id,
                    "target": inputNode.id,
                    "animated": true,
                    "sourceHandle": "right_handle",
                    "targetHandle": "left_handle"
                },
                {
                    "id": `xy-edge__${inputNode.id}right_handle-${ragNode.id}left_handle`,
                    "type": "customEdge",
                    "source": inputNode.id,
                    "target": ragNode.id,
                    "animated": true,
                    "sourceHandle": "right_handle",
                    "targetHandle": "left_handle"
                },
                {
                    "id": `xy-edge__${ragNode.id}right_handle-${inputNode.id}left_handle`,
                    "type": "customEdge",
                    "source": ragNode.id,
                    "target": inputNode.id,
                    "animated": true,
                    "sourceHandle": "right_handle",
                    "targetHandle": "left_handle"
                }
            ],
            "nodes": [
                {
                    "id": startNode.id,
                    "data": startNode,
                    "type": "flowNode",
                    "dragging": false,
                    "measured": {
                        "width": 334,
                        "height": 134
                    },
                    "position": {
                        "x": 469,
                        "y": 150
                    },
                    "selected": false
                },
                {
                    "id": inputNode.id,
                    "data": inputNode,
                    "type": "flowNode",
                    "dragging": false,
                    "measured": {
                        "width": 334,
                        "height": 150
                    },
                    "position": {
                        "x": 884,
                        "y": 149
                    },
                    "selected": false
                },
                {
                    "id": ragNode.id,
                    "data": ragNode,
                    "type": "flowNode",
                    "dragging": false,
                    "measured": {
                        "width": 334,
                        "height": 1162
                    },
                    "position": {
                        "x": 1328,
                        "y": 182
                    },
                    "selected": false
                }
            ],
            "viewport": {
                "x": 192,
                "y": -45,
                "zoom": 0.5
            }
        }
    }
}