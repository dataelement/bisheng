// src/features/chat-config/ChatConfig.tsx
import { Button } from "@/components/bs-ui/button";
import { Card, CardContent } from "@/components/bs-ui/card";
import { toast, useToast } from "@/components/bs-ui/toast/use-toast";
import { generateUUID } from "@/components/bs-ui/utils";
import { locationContext } from "@/contexts/locationContext";
import { userContext } from "@/contexts/userContext";
import { getWorkstationConfigApi, setWorkstationConfigApi } from "@/controllers/API";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { useContext, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { FormInput } from "./FormInput";
import { Model, ModelManagement } from "./ModelManagement";
import Preview from "./Preview";
import { useAssistantStore } from "@/store/assistantStore";
import { Search, Star, X } from "lucide-react";
import { ModelSelect } from "@/pages/ModelPage/manage/tabs/KnowledgeModel";
import { t } from "i18next";
import { sopApi } from "@/controllers/API/linsight";
import { getAssistantToolsApi } from "@/controllers/API/assistant";
import { useAssistantLLmModel } from "@/pages/ModelPage/manage";
import ToolSelector from "@/components/Linsight/ToolSelector";
import SopFormDrawer from "@/components/Linsight/SopFormDrawer";
import SopTable from "@/components/Linsight/SopTable";

export interface FormErrors {
    sidebarSlogan: string;
    welcomeMessage: string;
    functionDescription: string;
    inputPlaceholder: string;
    modelNames: string[] | string[][];
    webSearch?: Record<string, string>; // 新增动态错误存储
    systemPrompt: string;
    model: string;
    kownledgeBase: string;
}
export interface AssistantState {
    task_model: string;
    summary_model: string;
    // 其他现有字段...
}
export interface ChatConfigForm {
    menuShow: boolean;
    systemPrompt: string;
    sidebarIcon: {
        enabled: boolean;
        image: string;
        relative_path: string;
    };
    assistantIcon: {
        enabled: boolean;
        image: string;
        relative_path: string;
    };
    sidebarSlogan: string;
    welcomeMessage: string;
    functionDescription: string;
    inputPlaceholder: string;
    models: Model[];
    maxTokens: number;
    voiceInput: {
        enabled: boolean;
        model: string;
    };
    webSearch: {
        enabled: boolean;
        tool: string;
        params: {
            api_key?: string;
            base_url?: string;
            engine?: string;
        },
        prompt: string;
    };
    knowledgeBase: {
        enabled: boolean;
        prompt: string;
    };
    fileUpload: {
        enabled: boolean;
        prompt: string;
    };
}

export default function index() {

    const [keywords, setKeywords] = useState('');
    const [datalist, setDatalist] = useState([]);
    const [total, setTotal] = useState(1);
    const [loading, setLoading] = useState(false);
    const [page, setPage] = useState(1);
    const [pageSize] = useState(10);
    const [selectedTools, setSelectedTools] = useState([]);
    const [showToolSelector, setShowToolSelector] = useState(false);
    const [toolSearchTerm, setToolSearchTerm] = useState('');
    const [pageInputValue, setPageInputValue] = useState('1');
    const [activeToolTab, setActiveToolTab] = useState<'builtin' | 'api' | 'mcp'>('builtin');
    const [manuallyExpandedItems, setManuallyExpandedItems] = useState<string[]>([]);
    const [deleteConfirmModal, setDeleteConfirmModal] = useState({
        open: false,
        title: '确认删除',
        content: '',
        onConfirm: () => { },
        isBatch: false
    });
    // 在组件顶部添加表单状态
    const [formData, setFormData] = useState<ChatConfigForm>({
        menuShow: false,
        systemPrompt: '',
        sidebarIcon: {
            enabled: true,
            image: '',
            relative_path: ''
        },
        assistantIcon: {
            enabled: true,
            image: '',
            relative_path: ''
        },
        sidebarSlogan: '',
        welcomeMessage: '',
        functionDescription: '',
        inputPlaceholder: '请输入任务，然后交给BISHENG灵思', // 默认值
        models: [],
        maxTokens: 15000,
        voiceInput: {
            enabled: false,
            model: ''
        },
        webSearch: {
            enabled: true,
            tool: 'bing',
            params: {},
            prompt: ''
        },
        knowledgeBase: {
            enabled: true,
            prompt: ''
        },
        fileUpload: {
            enabled: true,
            prompt: ''
        }
    });
    const [toolsData, setToolsData] = useState({
        builtin: [],
        api: [],
        mcp: []
    });
    const { llmOptions, embeddings } = useAssistantLLmModel()
    const fetchTools = async (type: 'builtin' | 'api' | 'mcp') => {
        setLoading(true);
        try {
            let res;
            if (type === 'builtin') {
                res = await getAssistantToolsApi('default');
            } else if (type === 'api') {
                res = await getAssistantToolsApi('custom');
            } else {
                res = await getAssistantToolsApi('mcp');
            }
            setToolsData(prev => ({ ...prev, [type]: res || [] }));
        } catch (error) {
            toast({ variant: 'error', description: `获取${type === 'builtin' ? '内置' : type === 'api' ? 'API' : 'MCP'}工具失败` });
        } finally {
            setLoading(false);
        }
    };

    // 根据当前tab加载数据
    useEffect(() => {
        if (!toolsData[activeToolTab].length) {
            fetchTools(activeToolTab);
        }
    }, [activeToolTab]);
    useEffect(() => {
        console.log('当前分页状态:', {
            page,
            total,
            pageSize,
            totalPages: Math.ceil(total / pageSize),
            datalistLength: datalist.length
        });
    }, [page, total, datalist]);
    useEffect(() => {
        setPageInputValue(page.toString());
    }, [page]);
    const filteredTools = useMemo(() => {
        const currentTools = toolsData[activeToolTab] || [];
        const searchTerm = (toolSearchTerm || '').toString().toLowerCase();

        if (!searchTerm) return currentTools;

        return currentTools
            .map(tool => {
                const toolNameMatch = tool.name.toLowerCase().includes(searchTerm);
                const toolDescMatch = (tool.description || '').toLowerCase().includes(searchTerm);
                const matchedChildren = tool.children?.filter(child =>
                    child.name.toLowerCase().includes(searchTerm) ||
                    (child.desc || '').toLowerCase().includes(searchTerm)
                );
                if (toolNameMatch || toolDescMatch || matchedChildren?.length) {
                    return {
                        ...tool,
                        children: tool.children || [],
                        _forceExpanded: true
                    };
                }

                return null;
            })
            .filter(Boolean);
    }, [toolsData, activeToolTab, toolSearchTerm]);

    // 控制展开状态的value
    const expandedItems = useMemo(() => {
        const searchExpanded = toolSearchTerm
            ? filteredTools.filter(tool => tool._forceExpanded).map(tool => tool.id)
            : [];
        return [...new Set([...searchExpanded, ...manuallyExpandedItems])];
    }, [filteredTools, toolSearchTerm, manuallyExpandedItems]);
    useEffect(() => {
        sopApi.getSopList({ page_size: 10, page: 1, keywords: '' })
            .then(res => {
                setDatalist(res.items || []);  // 直接设置 datalist
            });
    }, []);
    const fetchData = async (params = {}) => {
        setLoading(true);
        try {
            const res = await sopApi.getSopList({
                page_size: params.pageSize || pageSize,
                page: params.page || page,
                keywords: params.keyword || keywords
            });

            setDatalist(res.items || []);

            const hasItems = res.items && res.items.length > 0;
            const calculatedTotal = hasItems ? Math.max(res.total || 0, (params.page || page) * pageSize) : 0;

            setTotal(calculatedTotal);
        } catch (error) {
            console.error('请求失败:', error);
            toast({ variant: 'error', description: '搜索失败，请稍后重试' });
        } finally {
            setLoading(false);
        }
    };
    useEffect(() => {
        fetchData({ page: 1, pageSize: 10, keyword: '' });
    }, []);
    const [isDrawerOpen, setIsDrawerOpen] = useState(false);
    const [isEditing, setIsEditing] = useState(false); // 标记当前是否为编辑模式
    const [currentSopId, setCurrentSopId] = useState(null); // 当前编辑的SOP ID
    // 切换工具选中状态
    const toggleTool = (tool) => {
        setSelectedTools(prev => {
            const existingIndex = prev.findIndex(t => t.id === tool.id);
            if (existingIndex >= 0) {
                return [...prev.slice(0, existingIndex), ...prev.slice(existingIndex + 1)];
            } else {
                return [...prev, tool];
            }
        });
    };

    const isToolSelected = (toolId) => {
        return selectedTools.some(t => t.id === toolId);
    };
    let { assistantState, dispatchAssistant } = useAssistantStore();
    const {
        handleInputChange,
        handleSave
    } = useChatConfig(assistantState, selectedTools, toolsData);

    // 非admin角色跳走
    const { user } = useContext(userContext);
    const navigate = useNavigate()
    useEffect(() => {
        if (user.user_id && user.role !== 'admin') {
            navigate('/build/apps')
        }
    }, [user])
    const removeTool = (index) => {
        const newTools = [...selectedTools];
        newTools.splice(index, 1);
        setSelectedTools(newTools);
    };
    const handleDragEnd = (result) => {
        if (!result.destination) return;

        // 防止拖拽到无效位置
        if (result.destination.index === result.source.index) return;

        const newSelectedTools = [...selectedTools];
        const [removed] = newSelectedTools.splice(result.source.index, 1);
        newSelectedTools.splice(result.destination.index, 0, removed);

        setSelectedTools(newSelectedTools);
    };


    const [selectedItems, setSelectedItems] = useState([]);
    const [sortConfig, setSortConfig] = useState({ key: null, direction: 'asc' });
    const handleSearch = (keyword: string, resetPage: boolean = false) => {
        const newKeywords = keyword;
        const newPage = resetPage || newKeywords.trim() === '' ? 1 : page;

        // 直接调用 fetchData，不依赖 useEffect
        fetchData({
            keyword: newKeywords,
            page: newPage,
            pageSize
        });

        // 更新状态
        setKeywords(newKeywords);
        if (newPage !== page) {
            setPage(newPage);
        }
    };
    const handlePageChange = (newPage: number) => {
        if (newPage === page || loading) return;

        const safeTotalPages = Math.max(1, Math.ceil(total / pageSize));

        newPage = Math.max(1, Math.min(newPage, safeTotalPages));

        setPage(newPage);
        fetchData({
            page: newPage,
            keyword: keywords,
            pageSize
        });
    };

    const handlePageInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        const value = e.target.value;
        if (value === '' || /^[1-9]\d*$/.test(value)) {
            setPageInputValue(value);
        }
    };

    const handlePageInputConfirm = () => {
        if (loading) return;

        if (pageInputValue.trim() === '') return;

        const pageNum = parseInt(pageInputValue);

        if (pageNum !== page) {
            setPage(pageNum);
            fetchData({
                page: pageNum,
                keyword: keywords
            });
        }

    };

    // 添加回车键支持
    const handleKeyDown = (e: React.KeyboardEvent) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            handlePageInputConfirm();
        }
    };
    const handleSelectItem = (id) => {
        setSelectedItems(prev =>
            prev.includes(id)
                ? prev.filter(itemId => itemId !== id)
                : [...prev, id]
        );
    };
    const handleSort = (key: string, direction: 'asc' | 'desc') => {
        setLoading(true);
        setSortConfig({ key, direction });

        // 调用API进行服务端排序
        sopApi.getSopList({
            page_size: pageSize,
            page: 1,
            keywords: keywords,
            sort: direction,
        })
            .then(res => {
                setDatalist(res.items || []);
                setTotal(res.total || 0);
                setPage(1);
                setPageInputValue('1');
            })
            .catch(error => {
                console.error('排序请求失败:', error);
                toast({ variant: 'error', description: '排序失败，请稍后重试' });
            })
            .finally(() => {
                setLoading(false);
            });
    };

    const handleBatchDelete = async () => {
        try {
            await sopApi.batchDeleteSop(selectedItems);
            setSelectedItems([]);
            toast({
                variant: 'success',
                description: `成功删除 ${selectedItems.length} 个SOP`
            });
            fetchData();
        } catch (error) {
            toast({
                variant: 'error',
                description: '删除失败，请稍后重试'
            });
        }
    };

    const handleSelectAll = (e) => {
        if (e.target.checked) {
            setSelectedItems(datalist.map(item => item.id));
        } else {
            setSelectedItems([]);
        }
    };
    // const [isBatchDeleteModalOpen, setIsBatchDeleteModalOpen] = useState(false);
    const [sopForm, setSopForm] = useState({
        id: '',
        name: '',
        description: '',
        content: '',
        rating: 0
    });

    const resetSopForm = () => {
        setSopForm({
            id: '',
            name: '',
            description: '',
            content: '',
            rating: 0
        });
        setIsEditing(false);
        setCurrentSopId(null);
    };
    const handleSaveSOP = async () => {
        try {
            const requestData = {
                name: sopForm.name.trim(),
                description: sopForm.description.trim(),
                content: sopForm.content.trim(),
                rating: sopForm.rating
            };

            if (isEditing && sopForm.id) {
                // 更新操作
                await sopApi.updateSop({
                    id: sopForm.id,
                    ...requestData
                });
                toast({ variant: 'success', description: 'SOP更新成功' });
            } else {
                // 新建操作
                await sopApi.addSop(requestData);
                toast({ variant: 'success', description: 'SOP创建成功' });
            }

            setIsDrawerOpen(false);
            fetchData(); // 刷新列表
            resetSopForm(); // 重置表单
        } catch (error) {
            console.error('保存SOP失败:', error);
            toast({
                variant: 'error',
                description: isEditing ? '更新SOP失败' : '创建SOP失败',
                details: error.message || '请检查数据并重试'
            });
        }
    };

    const handleEdit = (id: string) => {
        const sopToEdit = datalist.find(item => item.id === id);
        if (!sopToEdit) {
            toast({ variant: 'warning', description: '未找到要编辑的SOP' });
            return;
        }

        setIsEditing(true);
        setCurrentSopId(id);
        setSopForm({
            id: sopToEdit.id,
            name: sopToEdit.name || '',
            description: sopToEdit.description || '',
            content: sopToEdit.content || '',
            rating: sopToEdit.rating || 0
        });
        setIsDrawerOpen(true);
    };

    const handleDelete = (id: string) => {
        setDeleteConfirmModal({
            open: true,
            title: '',
            content: '确认删除该SOP吗？',
            onConfirm: async () => {
                try {
                    await sopApi.deleteSop(id);
                    toast({
                        variant: 'success',
                        description: 'SOP删除成功'
                    });
                    if (datalist.length === 1 && page > 1) {
                        setPage(page - 1);
                    } else {
                        fetchData();
                    }
                } catch (error) {
                    console.error('删除SOP失败:', error);
                    toast({
                        variant: 'error',
                        description: '删除失败',
                        details: error.message || '请稍后重试'
                    });
                }
            },
            isBatch: false
        });
    };
    return (
        <div className=" h-full overflow-y-scroll scrollbar-hide relative bg-background-main">
            <Card className="rounded-none">
                <CardContent className="pt-4 relative  ">
                    <div className="w-full  max-h-[calc(100vh-180px)] overflow-y-scroll scrollbar-hide">
                        <FormInput
                            label="输入框提示语"
                            value=""
                            placeholder="请输入任务，然后交给BISHENG灵思"
                            maxLength={1000}
                            onChange={(v) => {
                                setFormData(prev => ({
                                    ...prev,
                                    inputPlaceholder: v
                                }));
                            }} error={""} />
                        {/* <div className="mb-6">
                            <p className="text-lg font-bold mb-2">灵思模型</p>
                                        <ModelSelect
                                                close
                                                label={t('任务执行模型')}
                                                 tooltipText={t('建议使用能力最强的模型，以获得更佳任务执行效果')}
                                                  value={assistantState.task_model}
                                                options={embeddings}
                                                onChange={(val) => dispatchAssistant("setting", { task_model: val })}
                                            />
                            <div className="mb-6 mt-6">
                                <ModelSelect
                                   close
                                  label={t('任务信息摘要模型')}
                tooltipText={t('用于工具调用信息摘要和标题生成等场景，建议使用参数量小、响应速度快的模型')}
               value={assistantState.summary_model}
                                     options={llmOptions}
                                     onChange={(val) => dispatchAssistant("setting", { summary_model: val })}
                                />
                            </div>
                        </div> */}
                        <div className="mb-6">
                            <p className="text-lg font-bold mb-2">灵思可选工具</p>
                            <ToolSelector
                                selectedTools={selectedTools}
                                toggleTool={toggleTool}
                                removeTool={removeTool}
                                isToolSelected={isToolSelected}
                                handleDragEnd={handleDragEnd}
                                showToolSelector={showToolSelector}
                                setShowToolSelector={setShowToolSelector}
                                toolsData={toolsData}
                                activeToolTab={activeToolTab}
                                setActiveToolTab={setActiveToolTab}
                                toolSearchTerm={toolSearchTerm}
                                setToolSearchTerm={setToolSearchTerm}
                                loading={loading}
                                filteredTools={filteredTools}
                                expandedItems={expandedItems}
                                setManuallyExpandedItems={setManuallyExpandedItems}
                            />
                        </div>

                        <div className="mb-6">
                            <p className="text-lg font-bold mb-2">灵思SOP管理</p>
                            <div className="flex items-center gap-2 mb-2">
                                {/* 搜索框 - 调整宽度 */}
                                <div className="relative flex-1 max-w-xs">
                                    <div className="relative">
                                        <input
                                            type="text"
                                            placeholder="搜索SOP"
                                            className="w-full pl-10 pr-3 py-1.5 text-sm border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                                            value={keywords}
                                            onChange={(e) => {
                                                const newValue = e.target.value;
                                                setKeywords(newValue);
                                                handleSearch(newValue, newValue.trim() === '');
                                            }}
                                            onKeyDown={(e) => {
                                                if (e.key === 'Enter') {
                                                    handleSearch(keywords);
                                                }
                                            }}
                                        />
                                        <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-gray-400" />
                                    </div>
                                </div>

                                {/* 按钮组 - 调整大小和间距 */}
                                <div className="flex gap-2">
                                    <Button
                                        variant="default"
                                        size="sm"
                                        onClick={() => {
                                            setIsEditing(false);
                                            setCurrentSopId(null);
                                            setSopForm({
                                                id: '',
                                                name: '',
                                                description: '',
                                                content: '',
                                                rating: 0
                                            });
                                            setIsDrawerOpen(true);
                                        }}
                                    >
                                        新建SOP
                                    </Button>
                                    <Button
                                        variant="outline"
                                        size="sm"
                                        disabled={selectedItems.length === 0}
                                        onClick={() => {
                                            setDeleteConfirmModal({
                                                open: true,
                                                title: '',
                                                content: `确认批量删除${selectedItems.length}个SOP吗？`,
                                                onConfirm: handleBatchDelete,
                                                isBatch: true
                                            });
                                        }}
                                        className={selectedItems.length === 0 ? 'opacity-50 cursor-not-allowed' : ''}
                                    >
                                        批量删除
                                    </Button>
                                </div>
                            </div>
                            {/* 表格区域 */}
                            <SopTable datalist={datalist} selectedItems={selectedItems} handleSelectItem={handleSelectItem} handleSelectAll={handleSelectAll} handleSort={handleSort} handleEdit={handleEdit} handleDelete={handleDelete} page={page} pageSize={pageSize} total={total} loading={loading} pageInputValue={pageInputValue} handlePageChange={handlePageChange} handlePageInputChange={handlePageInputChange} handlePageInputConfirm={handlePageInputConfirm} handleKeyDown={handleKeyDown} />
                            {deleteConfirmModal.open && (
                                <div className="fixed inset-0 z-[1000] bg-opacity-50 flex items-center justify-center">
                                    <div className="relative rounded-lg p-6 w-[500px]  h-[150px]" style={{ background: 'white', opacity: 1, border: '1px solid #e5e7eb' }}>
                                        <button
                                            className="absolute top-3 right-3 text-gray-400 hover:text-gray-600"
                                            onClick={() => setDeleteConfirmModal(prev => ({ ...prev, open: false }))}
                                        >
                                            ×
                                        </button>
                                        <p className="text-gray-600 text-center mb-6">{deleteConfirmModal.content}</p>
                                        <div className="flex justify-between space-x-3">
                                            <Button
                                                variant="ghost"
                                                onClick={() => setDeleteConfirmModal(prev => ({ ...prev, open: false }))}
                                            >
                                                取消
                                            </Button>
                                            <Button
                                                type="button"
                                                onClick={() => {
                                                    deleteConfirmModal.onConfirm();
                                                    setDeleteConfirmModal(prev => ({ ...prev, open: false }));
                                                }}
                                            >
                                                确认删除
                                            </Button>
                                        </div>
                                    </div>
                                </div>
                            )}


                            <SopFormDrawer isDrawerOpen={isDrawerOpen} setIsDrawerOpen={setIsDrawerOpen} isEditing={isEditing} sopForm={sopForm} setSopForm={setSopForm} handleSaveSOP={handleSaveSOP} />
                        </div>
                    </div>
                    <div className="flex justify-end gap-4 absolute bottom-4 right-4">
                        <Preview onBeforView={handleSave} />
                        <Button onClick={() => handleSave(formData)}>保存</Button>
                    </div>
                </CardContent>
            </Card>
        </div>
    );
}




const useChatConfig = (assistantState: {
    model_name: string; task_model: string;
    summary_model: string;
},
    selectedTools: Array<{ id: string | number; name: string }>,
    toolsData: { builtin: any[]; api: any[]; mcp: any[] }) => {

    const { toast } = useToast();
    const { llmOptions, embeddings } = useAssistantLLmModel();

    const getModelDisplayName = (modelId: string) => {
        const allModels = [...llmOptions, ...embeddings];
        const targetId = String(modelId);

        for (const group of allModels) {
            if (String(group.value) === targetId) {
                return group.label;
            }
            if (group.children) {
                const childModel = group.children.find(child => String(child.value) === targetId);
                if (childModel) {
                    return childModel.label;
                }
            }
        }
        return `未知模型 (ID: ${modelId})`;
    };
    const safeClone = (obj: any) => {
        const seen = new WeakSet();
        return JSON.parse(JSON.stringify(obj, (key, value) => {
            if (typeof value === 'object' && value !== null) {
                if (seen.has(value)) {
                    return;
                }
                seen.add(value);
            }
            return value;
        }));
    };
    const handleSave = async (formData: any) => {
        const dataToSave = {
            ...safeClone(formData),
            sidebarSlogan: formData.sidebarSlogan?.trim() || '',
            welcomeMessage: formData.welcomeMessage?.trim() || '',
            functionDescription: formData.functionDescription?.trim() || '',
            inputPlaceholder: formData.inputPlaceholder?.trim() || "请输入任务，然后交给 BISHENG 灵思",
            maxTokens: formData.maxTokens || 15000,

            inspirationConfig: {
                input_placeholder: formData.inputPlaceholder?.trim() || "请输入任务，然后交给 BISHENG 灵思",
                task_model: {
                    key: generateUUID(4),
                    id: assistantState.task_model,
                    name: "",
                    displayName: getModelDisplayName(assistantState.task_model)
                },

                task_summary_model: {
                    key: generateUUID(4),
                    id: assistantState.summary_model,
                    name: "",
                    displayName: getModelDisplayName(assistantState.summary_model)
                },

                tools: selectedTools.map(tool => {
                    const parentTool = [...toolsData.builtin, ...toolsData.api, ...toolsData.mcp]
                        .find(parent =>
                            parent.children &&
                            parent.children.some(child => child.id === tool.id)
                        );

                    return {
                        id: parentTool?.id || tool.id,
                        name: parentTool?.name || tool.name,
                        children: parentTool
                            ? [{ id: tool.id, name: tool.name }]
                            : []
                    };
                })
            }
        };

        try {
            const res = await setWorkstationConfigApi(dataToSave);
            console.log(res, dataToSave);

            if (res) {
                toast({ variant: 'success', description: '配置保存成功' });
                return true;
            }
        } catch (error) {
            toast({ variant: 'error', description: '保存失败' });
            return false;
        }
    };

    return { handleSave };
};

function setTotal(arg0: any) {
    throw new Error("Function not implemented.");
}
