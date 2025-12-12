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
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";

export default function FileUploadStep4({ data, kId }) {
    const { t } = useTranslation('knowledge');
    const [finish, setFinish] = useState(true)
    const navigate = useNavigate()
    const { id: kid } = useParams()

    const [files, setFiles] = useState([])
    const timerRef = useRef(null); // Polling timer reference
    const fileIdsRef = useRef([]); // File ID list reference
    const processingRef = useRef(new Set()); // Track processing file IDs
    const isPollingRef = useRef(false); // Prevent polling concurrency
    const hasInitialized = useRef(false);
    const [premainingFileIds, setPremainingFileIds] = useState([]); // Track remaining file IDs

    // Initialize file status (executed only once)
    useEffect(() => {
        if (data.length > 0 && !hasInitialized.current) {

            const initialFiles = data.map(item => ({
                id: item.id || item.fileId, // Frontend file unique identifier
                fileName: item.fileName,
                error: false,
                reason: '',
                progress: 'await'
            }));

            setFiles(initialFiles);

            // Key: fileIdsRef and processingRef both store frontend file IDs (ensure data consistency)
            const frontEndFileIds = initialFiles.map(file => file.id);
            fileIdsRef.current = frontEndFileIds;
            processingRef.current.clear();
            frontEndFileIds.forEach(id => processingRef.current.add(id)); // Use same batch of IDs

            setFinish(false);
            hasInitialized.current = true;
        }
        setPremainingFileIds(data.reduce((res, item) => {
            res[item.id] = true;
            return res;
        }, {}))

    }, [data]);

    // Poll file status (complete fix version)
    useEffect(() => {
        // 1. Define polling function first (must be defined before calling, fix "undefined when called" issue)
        const pollFilesStatus = async () => {
            if (isPollingRef.current) return;
            isPollingRef.current = true;

            try {
                // Fix pending file ID exception (previously was [0], should actually take frontend file ID)
                const pendingFileIds = Array.from(processingRef.current);
                console.log("Correct pending file IDs:", pendingFileIds); // Should now be ['fe9d1b', 'd3b66c', ...]

                // Keep API parameters unchanged (backend may filter by knowledge_id, file_ids can pass frontend IDs or leave empty)
                const res = await readFileByLibDatabase({
                    id: kid || kId,
                    page: 0,
                    pageSize: 0,
                    file_ids: pendingFileIds
                });

                // setFiles status update logic in polling function (add logs after cleanup)
                setFiles(prev => {
                    const updatedFiles = [...prev];
                    const resMap = new Map(res.data.map(item => [item.file_name.toLowerCase().trim(), item])); // Build Map with file names for faster matching

                    updatedFiles.forEach((file, index) => {
                        const resItem = resMap.get(file.fileName.toLowerCase().trim());
                        if (resItem && resItem.status === 2) {
                            // Double confirmation: remove current file id from processingRef
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
                            updatedFiles[index] = { ...file, progress: 'end', error: true, reason: resItem.remark || t('parseFailed') };
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

        // 3. Handle "no files" case (only then call the already defined pollFilesStatus)
        if (fileIdsRef.current.length === 0) {
            const timer = setTimeout(() => {
                if (fileIdsRef.current.length > 0) {
                    pollFilesStatus(); // Function is now defined, can be called normally
                }
            }, 100);
            return () => clearTimeout(timer);
        }

        // 4. When there are files, poll immediately + schedule polling
        if (fileIdsRef.current.length > 0) {
            pollFilesStatus(); // Execute first time immediately
            timerRef.current = setInterval(pollFilesStatus, 5000);
        } else {
            setFinish(true);
        }

        // 5. Clean up timer
        return () => {
            if (timerRef.current) clearInterval(timerRef.current);
        };
    }, [kid, kId, t]); // Add t to dependencies

    useEffect(() => {
        return () => {
            hasInitialized.current = false;
        };
    }, []);

    // Check if all files are completed
    useEffect(() => {
        // Mark as complete when processing set is empty
        if (processingRef.current.size === 0 && fileIdsRef.current.length > 0) {
            console.log('所有文件处理完成');
            if (timerRef.current) {
                clearInterval(timerRef.current);
            }
            setFinish(true);
        } else {
            setFinish(false);
        }
    }, [files]); // Depend on file status changes

    console.log('files :>> ', files);

    let finalId = kid;
    if (kId) {
        finalId = kId.replace(/\D/g, '');
    }

    const [details] = useKnowledgeDetails([finalId])

    const handleCreateFlow = async (params) => {
        const model = await getLlmDefaultModel()

        const flow = await getKnowledgeDefaultFlowTemplate(finalId, details[0]?.name || '', model.model_id)
        const res = await captureAndAlertRequestErrorHoc(createWorkflowApi(
            t('documentKnowledgeQa') + generateUUID(5),
            t('retrieveDocumentKnowledge'),
            "",
            flow))
        history.pushState(null, null, __APP_ENV__.BASE_URL + '/build/apps');

        navigate('/flow/' + res.id);
    }

    return <div className={`max-w-[1400px] mx-auto px-20 pt-4 relative`}>
        <div className="flex gap-4">
            <div className="flex-1">
                <h1 className="text-3xl text-primary mt-2">{finish ? t('documentDataParsingCompleted') : t('documentDataBeingPrepared')}</h1>
                <p className="text-base text-gray-500 mt-2">{t('youCanReturn')}</p>
                <div className="overflow-y-auto mt-4 space-y-2 pb-10 max-h-[calc(100vh-400px)]">
                    {files.map(item => premainingFileIds[item.id] ? <ProgressItem analysis key={item.id} item={item} /> : null)}
                </div>
                <div className="flex justify-end gap-4">
                    <Button onClick={() => navigate(-1)}>
                        {t('returnToKnowledgeBase')}
                    </Button>
                </div>
            </div>
            {finish && <div className="w-96 pt-24">
                <CardComponent
                    data={null}
                    type='assist'
                    title={t('buildKnowledgeBaseQaAgent')}
                    description={<p>{t('afterDocumentParsing')}</p>}
                    onClick={handleCreateFlow}
                ></CardComponent>
            </div>}
        </div>
    </div>
};

// Keep getKnowledgeDefaultFlowTemplate function unchanged
const getKnowledgeDefaultFlowTemplate = async (kid, kname, modelId) => {
    const templates = await getWorkflowNodeTemplate()
    let startNode = null
    let inputNode = null
    let ragNode = null

    templates.forEach(node => {
        const nodeCopy = JSON.parse(JSON.stringify(node)); // Deep copy node

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