
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

export default function FileUploadStep4({ data }) {
    const [finish, setFinish] = useState(true)
    const navigate = useNavigate()
    const { id: kid } = useParams()

    const [files, setFiles] = useState([])
    const timerRef = useRef(null); // 轮询定时器引用
    const fileIdsRef = useRef([]); // 文件ID列表引用
    // 初始化文件状态
    useEffect(() => {
        const initialFiles = data.map(item => ({
            id: item.fileId,
            fileName: item.fileName,
            error: false,
            reason: '',
            progress: 'await' // 初始状态设为解析中
        }));
        setFiles(initialFiles);
        fileIdsRef.current = data.map(item => item.fileId); // 保存文件ID列表
    }, [data]);


    // 轮询文件状态
    useEffect(() => {
        // 如果文件列表为空，直接完成
        if (fileIdsRef.current.length === 0) {
            setFinish(true);
            return;
        }

        // 轮询函数
        const pollFilesStatus = async () => {
            try {
                const res = await readFileByLibDatabase({
                    id: kid,
                    page: 0,
                    pageSize: 0,
                    file_ids: fileIdsRef.current
                });

                // 更新文件状态
                setFiles(prev => {
                    const resMap = new Map(res.data.map(item => [item.id, item]));
                    return prev.map(file => {
                        if (resMap.has(file.id)) {
                            const resItem = resMap.get(file.id);
                            let progress = 'await';
                            let error = false;
                            let reason = '';

                            if (resItem.status === 2) {
                                progress = 'end'; // 成功
                            } else if (resItem.status === 3) {
                                progress = 'end'; // 失败
                                error = true;
                                reason = resItem.remark;
                            }

                            return { ...file, progress, error, reason };
                        }
                        return file;
                    });
                });
            } catch (e) {
                console.error("轮询文件状态出错:", e);
            }
        };

        // 立即执行第一次轮询，然后每5秒轮询一次
        pollFilesStatus();
        timerRef.current = setInterval(pollFilesStatus, 3000 + fileIdsRef.current.length * 10);

        // 清理定时器
        return () => clearInterval(timerRef.current);
    }, [kid]);

    // 检查所有文件是否完成
    useEffect(() => {
        // 如果所有文件都已完成（成功或失败）
        if (files.length > 0 && files.every(f => f.progress === 'end')) {
            clearInterval(timerRef.current);
            setFinish(true);
        } else {
            setFinish(false);
        }
    }, [files]);
    console.log('fukes :>> ', data, files);

    const [details] = useKnowledgeDetails([kid])
    const handleCreateFlow = async (params) => {
        const model = await getLlmDefaultModel()
        const flow = await getKnowledgeDefaultFlowTemplate(kid, details[0].name, model.model_id)
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