// src/features/chat-config/ChatConfig.tsx
import { Button } from "@/components/bs-ui/button";
import { Card, CardContent } from "@/components/bs-ui/card";
import { toast, useToast } from "@/components/bs-ui/toast/use-toast";

import { userContext } from "@/contexts/userContext";
import { getWorkstationConfigApi, setWorkstationConfigApi } from "@/controllers/API";
import { useCallback, useContext, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { FormInput } from "./FormInput";
import { Model, ModelManagement } from "./ModelManagement";
import Preview from "./Preview";
import { useAssistantStore } from "@/store/assistantStore";
import { Search, Star, X } from "lucide-react";
import { t } from "i18next";
import { sopApi} from "@/controllers/API/linsight";
import { getAssistantToolsApi } from "@/controllers/API/assistant";
import ToolSelector from "@/components/LinSight/ToolSelector";
import SopFormDrawer from "@/components/LinSight/SopFormDrawer";
import SopTable from "@/components/LinSight/SopTable";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { LoadIcon, LoadingIcon } from "@/components/bs-icons/loading";
import { cloneDeep } from "lodash-es";
import ImportFromRecordsDialog from "@/components/LinSight/SopFromRecord";


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

export default function index({ formData: parentFormData, setFormData: parentSetFormData }) {

    const [keywords, setKeywords] = useState('');
    const [datalist, setDatalist] = useState([]);
    const [total, setTotal] = useState(1);
    const [loading, setLoading] = useState(false);
    const [page, setPage] = useState(1);
    const [pageSize] = useState(10);
    const [batchDeleting, setBatchDeleting] = useState(false);
    const [selectedTools, setSelectedTools] = useState(() => {
        return parentFormData?.linsightConfig?.tools || [];
    });
    const [showToolSelector, setShowToolSelector] = useState(false);
    const [toolSearchTerm, setToolSearchTerm] = useState('');
    const [pageInputValue, setPageInputValue] = useState('1');
    const [activeToolTab, setActiveToolTab] = useState<'builtin' | 'api' | 'mcp'>('mcp');
    const [manuallyExpandedItems, setManuallyExpandedItems] = useState<string[]>([]);
    const [initialized, setInitialized] = useState(false);
    // const [importDialogOpen, setImportDialogOpen] = useState(false);
    const [deleteConfirmModal, setDeleteConfirmModal] = useState({
        open: false,
        title: '确认删除',
        content: '',
        onConfirm: () => { },
        isBatch: false
    });
    const defaultFormValues = {
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
        inputPlaceholder: '请输入你的任务目标，然后交给 BISHENG 灵思',
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
        },
        linsightConfig: {
            input_placeholder: '请输入你的任务目标，然后交给 BISHENG 灵思',
            tools: []
        }
    };
    const [formData, setFormData] = useState<ChatConfigForm>(parentFormData || defaultFormValues);
    const [toolsData, setToolsData] = useState({
        builtin: [],
        api: [],
        mcp: []
    });
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
            toast({ variant: 'error', description: `获取${type}工具失败` });
        } finally {
            setLoading(false);
        }
    };
    useEffect(() => {
        if (parentFormData) {
            setFormData(parentFormData);
        }
        if (parentFormData?.linsightConfig?.tools) {
            setSelectedTools(parentFormData.linsightConfig.tools);
        }
    }, [parentFormData]);

    useEffect(() => {
        parentSetFormData?.(formData);
    }, [formData]);
    useEffect(() => {
        setFormData(prev => ({
            ...prev,
            linsightConfig: {
                ...prev.linsightConfig,
                tools: selectedTools
            }
        }));
    }, [selectedTools]);
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


    const expandedItems = useMemo(() => {
        const searchExpanded = toolSearchTerm
            ? filteredTools.filter(tool => tool._forceExpanded).map(tool => tool.id)
            : [];
        return [...new Set([...searchExpanded, ...manuallyExpandedItems])];
    }, [filteredTools, toolSearchTerm, manuallyExpandedItems]);

    const fetchData = async (params: {
        page: number;
        pageSize: number;
        keyword?: string;
        sort?: 'asc' | 'desc';
    }) => {
        setLoading(true);
        try {
            const res = await sopApi.getSopList({
                page_size: params.pageSize,
                page: params.page,
                keywords: params.keyword || keywords,
                sort: params.sort,
            });

            setDatalist(res.items || []);

            const hasItems = res.items && res.items.length > 0;
            const calculatedTotal = hasItems ? Math.max(res.total || 0, (params.page || page) * pageSize) : 0;
            setTotal(calculatedTotal);
        } catch (error) {
            console.error('请求失败:', error);
            toast({ variant: 'error', description: '请求失败，请稍后重试' });
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
    const toggleTool = (tool, child) => {
        setSelectedTools(prev => {
            const parentIndex = prev.findIndex(t => t.id === tool.id);

            // 一级工具存在
            if (parentIndex > -1) {
                const parent = prev[parentIndex];
                const childIndex = parent.children.findIndex(c => c.id === child.id);

                // 创建新的子工具数组
                const newChildren = childIndex === -1
                    ? [...parent.children, child]  // 添加新子工具
                    : parent.children.filter((_, i) => i !== childIndex); // 移除已存在子工具

                // 更新或移除父级工具
                return newChildren.length > 0
                    ? [
                        ...prev.slice(0, parentIndex),
                        { ...parent, children: newChildren },
                        ...prev.slice(parentIndex + 1)
                    ]
                    : prev.filter(t => t.id !== tool.id);
            }

            // 一级工具不存在，直接添加
            return [...prev, { ...tool, children: [child] }];
        });
    };

    const isToolSelected = (toolId, childId) => {
        const parent = selectedTools.find(t => t.id === toolId);
        if (!parent) return false;
        return parent.children.some(c => c.id === childId);
        return selectedTools.some(t => t.id === toolId);
    };
    let { assistantState, dispatchAssistant } = useAssistantStore();
    const { handleSave } = useChatConfig(
        assistantState,
        selectedTools,
        toolsData,
        setFormData
    );

    // 非admin角色跳走
    const { user } = useContext(userContext);
    const navigate = useNavigate()

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
    useEffect(() => {
        if (!user.user_id) return;

        if (user.role !== 'admin') {
            navigate('/build/apps');
            return;
        }
        const loadInitialData = async () => {
            try {
                let config;
                if (!parentFormData) {
                    config = await getWorkstationConfigApi();
                } else {
                    config = parentFormData;
                }

                if (config) {
                    setFormData({
                        ...defaultFormValues,
                        ...config,
                        inputPlaceholder: config.inputPlaceholder ||
                            config.linsightConfig?.input_placeholder ||
                            defaultFormValues.inputPlaceholder,
                        linsightConfig: {
                            ...defaultFormValues.linsightConfig,
                            ...config.linsightConfig,
                            input_placeholder: config.linsightConfig?.input_placeholder || '',
                        }
                    });

                    const tools = config.linsightConfig?.tools || parentFormData?.linsightConfig?.tools;

                    if (tools?.length > 0) {
                        setSelectedTools(tools);
                    }
                }
            } catch (error) {
                toast({ variant: 'error', description: '初始化数据加载失败' });
            } finally {
                setInitialized(true);
            }
        };

        loadInitialData();
    }, [user]);

    useEffect(() => {
        if (initialized && !toolsData[activeToolTab].length) {
            fetchTools(activeToolTab);
        }
    }, [activeToolTab, initialized]);

    const [selectedItems, setSelectedItems] = useState([]);
    const [sortConfig, setSortConfig] = useState({ key: null, direction: '' });
    const handleSearch = (keyword: string, resetPage: boolean = false) => {
        const newKeywords = keyword;
        const newPage = resetPage || newKeywords.trim() === '' ? 1 : page;

        fetchData({
            keyword: newKeywords,
            page: newPage,
            pageSize
        });

        // 更新状态
        setKeywords(newKeywords);
        setPageInputValue(newPage.toString());
        if (newPage !== page) {
            setPage(newPage);
        }
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
    const handlePageChange = (newPage: number) => {
        if (newPage === page || loading) return;

        const safeTotalPages = Math.max(1, Math.ceil(total / pageSize));
        newPage = Math.max(1, Math.min(newPage, safeTotalPages));

        setPage(newPage);
        setPageInputValue(newPage.toString());

        const requestParams: any = {
            page: newPage,
            keyword: keywords,
            pageSize
        };


        if (sortConfig && sortConfig.direction) {
            requestParams.sort = sortConfig.direction;

        }

        fetchData(requestParams);
    };
 const handleBatchDelete = async () => {
    setBatchDeleting(true);
    try {
        await sopApi.batchDeleteSop(selectedItems);

        // 计算新的总数
        const newTotal = total - selectedItems.length;
        const newTotalPages = Math.ceil(newTotal / pageSize);
        
        // 确定新的当前页
        let newPage = page;
        
        if (datalist.length === selectedItems.length) {
            if (page > 1) {
                newPage = page - 1;
            } 
            else if (newTotal > 0) {
                newPage = 1;
            }
        }
        if (newPage > newTotalPages && newTotalPages > 0) {
            newPage = newTotalPages;
        }

        // 更新状态
        setTotal(newTotal);
        setSelectedItems([]);
        setPage(newPage);  // 确保更新page状态
        setPageInputValue(newPage.toString());

        // 重新获取数据
        fetchData({
            page: newPage,
            pageSize: pageSize,
            keyword: keywords,
        });

        toast({ 
            variant: 'success', 
            description: `成功删除 ${selectedItems.length} 个 SOP` 
        });
    } catch (error) {
        toast({ 
            variant: 'error', 
            description: '删除失败，请稍后重试' 
        });
    } finally {
        setBatchDeleting(false);
    }
};
    const handleSelectAll = useCallback(() => {
        const currentPageIds = datalist.map(item => item.id);
        if (currentPageIds.every(id => selectedItems.includes(id))) {
            setSelectedItems(prev => prev.filter(id => !currentPageIds.includes(id)));
        } else {
            setSelectedItems(prev => [...new Set([...prev, ...currentPageIds])]);
        }
    }, [datalist, selectedItems]);
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
            fetchData({
                page: 1,
                pageSize: 10,
                keyword: keywords
            }); // 刷新列表
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
        bsConfirm({
            title: '删除确认',
            desc: '确认删除该SOP吗？',
            showClose: true,
            okTxt: '确认删除',
            canelTxt: '取消',
            onOk(next) {
                sopApi.deleteSop(id)
                    .then(() => {
                        toast({
                            variant: 'success',
                            description: 'SOP删除成功'
                        });

                        setSelectedItems(prevItems => prevItems.filter(itemId => itemId !== id));

                        // 修复这里 - 确保传递正确的参数
                        if (datalist.length === 1 && page > 1) {
                            setPage(page - 1);
                            fetchData({
                                page: page - 1,
                                pageSize: pageSize,
                                keyword: keywords,
                            });
                        } else {
                            fetchData({
                                page: page,
                                pageSize: pageSize,
                                keyword: keywords,
                            });
                        }
                        next();
                    })
                    .catch(error => {
                        console.error('删除SOP失败:', error);
                        toast({
                            variant: 'error',
                            description: '删除失败',
                            details: error.message || '请稍后重试'
                        });
                    });
            },
            onCancel() {
            }
        });
    };

    const toggleGroup = useCallback((group: any, checked: boolean) => {
        setSelectedTools(prev => {
            const tools = prev.filter(t => t.id !== group.id);
            if (checked) {
                tools.push(cloneDeep(group));
            }

            return [...tools];
        });
    }, []);
    return (
        <div className=" h-full overflow-y-scroll scrollbar-hide relative bg-background-main">
            {loading && (
                <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
                    <LoadingIcon />
                </div>
            )}
            <Card className="rounded-none">
                <CardContent className="pt-4 relative  ">
                    <div className="w-full  max-h-[calc(100vh-180px)] overflow-y-scroll scrollbar-hide">
                        <FormInput
                            label="输入框提示语"
                            value={formData.linsightConfig.input_placeholder}
                            placeholder="请输入你的任务目标，然后交给 BISHENG 灵思"
                            maxLength={100}
                            onChange={(v) => {
                                setFormData(prev => ({
                                    ...prev,
                                    linsightConfig: {
                                        ...prev.linsightConfig,
                                        input_placeholder: v
                                    }

                                }));
                            }} error={""} />
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
                                toggleGroup={toggleGroup}
                            />
                        </div>

                        <div className="mb-6">
                            <p className="text-lg font-bold mb-2">灵思SOP管理</p>
                            {/* <p className="text-lg font-bold mb-2">灵思SOP库</p> */}

                            <div className="flex items-center gap-2 mb-2">
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

                                <div className="flex gap-2">
                                    {/* <Button
                                        variant="default"
                                        size="sm"
                                       onClick={() => setImportDialogOpen(true)}
                                    >
                                        从运行记录中导入
                                    </Button> */}
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
                                        disabled={selectedItems.length === 0 || batchDeleting}
                                        onClick={() => {
                                            bsConfirm({
                                                title: '批量删除确认',
                                                desc: `确认批量删除所选SOP吗？`,
                                                showClose: true,
                                                okTxt: '确认删除',
                                                canelTxt: '取消',
                                                onOk(next) {
                                                    handleBatchDelete();
                                                    next();
                                                },
                                                onCancel() {
                                                }
                                            });
                                        }}
                                    >
                                        {batchDeleting && <LoadIcon className=" mr-2 text-gray-600" />}
                                        {'批量删除'}

                                    </Button>
                                </div>
                            </div>
                            {/* <ImportFromRecordsDialog 
                                open={importDialogOpen} 
                                onOpenChange={setImportDialogOpen} 
                                /> */}
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


                            <SopFormDrawer
                                isDrawerOpen={isDrawerOpen}
                                setIsDrawerOpen={setIsDrawerOpen}
                                isEditing={isEditing}
                                sopForm={sopForm}
                                setSopForm={setSopForm}
                                handleSaveSOP={handleSaveSOP}
                                tools={selectedTools}
                            />
                        </div>
                    </div>
                    <div className="flex justify-end gap-4 absolute bottom-1 right-4">
                        <Preview onBeforView={() => handleSave(formData)} />
                        <Button onClick={() => handleSave(formData)}>保存</Button>
                    </div>
                </CardContent>
            </Card>
        </div>
    );
}




const useChatConfig = (
    assistantState: { model_name: string; task_model: string; summary_model: string },
    selectedTools: Array<{ id: string | number; name: string }>,
    toolsData: { builtin: any[]; api: any[]; mcp: any[] },
    setFormData: React.Dispatch<React.SetStateAction<ChatConfigForm>>,
    activeToolTab: 'builtin' | 'api' | 'mcp'
) => {
    const { toast } = useToast();

const handleSave = async (formData: ChatConfigForm) => {
  // 保留所有必要的字段
  console.log(formData, 'formData',selectedTools,22);
  
  const processedTools = selectedTools.map(tool => ({
    id: tool.id,
    name: tool.name,
    is_preset: tool.is_preset,
    tool_key: tool.tool_key,
    children: tool.children?.map(child => ({
      id: child.id,
      name: child.name,
      tool_key: child.tool_key,
      desc: child.desc 
    }))
  }));

  const dataToSave = {
    ...formData,
    linsightConfig: {
      input_placeholder: formData.linsightConfig?.input_placeholder || '',
      tools: processedTools
    }
  };

  try {
    const res = await setWorkstationConfigApi(dataToSave);
    if (res) {
      setFormData(dataToSave);
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
