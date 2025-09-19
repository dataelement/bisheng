// src/features/chat-config/ChatConfig.tsx
import SopFormDrawer from "@/components/LinSight/SopFormDrawer";
import ImportFromRecordsDialog from "@/components/LinSight/SopFromRecord";
import SopTable from "@/components/LinSight/SopTable";
import ToolSelectorContainer from "@/components/LinSight/ToolSelectorContainer";
import { UploadIcon } from "@/components/bs-icons";
import { LoadIcon, LoadingIcon } from "@/components/bs-icons/loading";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { Button } from "@/components/bs-ui/button";
import { Card, CardContent } from "@/components/bs-ui/card";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { message, toast, useToast } from "@/components/bs-ui/toast/use-toast";
import { locationContext } from "@/contexts/locationContext";
import { userContext } from "@/contexts/userContext";
import { getWorkstationConfigApi, setWorkstationConfigApi } from "@/controllers/API";
import { getAssistantToolsApi } from "@/controllers/API/assistant";
import { sopApi } from "@/controllers/API/linsight";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { useAssistantStore } from "@/store/assistantStore";
import { downloadFile } from "@/util/utils";
import { cloneDeep } from "lodash-es";
import { Search } from "lucide-react";
import { useCallback, useContext, useEffect, useMemo, useState } from "react";
import { useDropzone } from "react-dropzone";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { FormInput } from "./FormInput";
import { Model } from "./ModelManagement";
import Preview from "./Preview";
import { t } from "i18next";

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
    const [activeToolTab, setActiveToolTab] = useState<'builtin' | 'api' | 'mcp'>('builtin');
    const [manuallyExpandedItems, setManuallyExpandedItems] = useState<string[]>([]);
    const [initialized, setInitialized] = useState(false);
    const [importDialogOpen, setImportDialogOpen] = useState(false);
    const [localFileDialogOpen, setLocalFileDialogOpen] = useState(false);
    const [importFile, setImportFile] = useState<File | null>(null);
    const [importFiles, setImportFiles] = useState<File[]>([]);
    const [isImporting, setIsImporting] = useState(false);
    const [validationDialog, setValidationDialog] = useState({
        open: false,
        status_message: "共计划导入0条SOP，格式正确0条，错误0条"
    });
    const [importFilesData, setImportFilesData] = useState<File[]>([]);
    const [duplicateNames, setDuplicateNames] = useState<string[]>([]);
    const [duplicateDialogOpen, setDuplicateDialogOpen] = useState(false);
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
            input_placeholder: '灵思是一位擅长完成复杂任务的Agent助理，除了描述任务目标外，您还可以用通俗的语言描述希望如何实现，这将有助于得到符合您预期的结果~',
            tools: []
        }
    };
    const [formData, setFormData] = useState<ChatConfigForm>(parentFormData || defaultFormValues);
    const [toolsData, setToolsData] = useState({
        builtin: [],
        api: [],
        mcp: []
    });
    const [importFormData, setImportFormData] = useState<FormData | null>(null);

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

    //     const refreshSopList = () => {
    //   fetchData({
    //     page: page,
    //     pageSize: 10,
    //     keyword: keywords
    //   });
    // };
    const fetchData = async (params: {
        page: number;
        pageSize: number;
        keyword?: string;
        sort?: 'asc' | 'desc';
        showcase?: 0 | 1;
    }) => {
        setLoading(true);
        try {
            const res = await sopApi.getSopList({
                page_size: params.pageSize,
                page: params.page,
                keywords: params.keyword || '',
                // sort: params.sort,
                showcase: params.showcase,
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

                if (config && 'menuShow' in config) {
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
                } else {
                    setFormData((prev) => ({
                        ...prev,
                        ...config
                    }))
                }
            } catch (error) {
                toast({ variant: 'error', description: t('chatConfig.initLoadFailed') });
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
    const { t } = useTranslation()
    const { appConfig } = useContext(locationContext)
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

    // 关闭弹窗刷新下数据
    useEffect(() => {
        if (!importDialogOpen) {
            fetchData({
                keyword: '',
                page,
                pageSize
            });
        }
    }, [importDialogOpen])


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
                console.error('sort failed:', error);
                toast({ variant: 'error', description: t('chatConfig.sortFailed') });
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
            pageSize,
            showcase: showcaseFilter
        };


        if (sortConfig && sortConfig.direction) {
            requestParams.sort = sortConfig.direction;

        }

        fetchData(requestParams);
    };
    const [showcaseFilter, setShowcaseFilter] = useState<0 | 1 | undefined>(undefined);
    const handleShowcaseFilterChange = (val?: 0 | 1) => {
        setShowcaseFilter(val);
        fetchData({ page: 1, pageSize, keyword: keywords, sort: sortConfig.direction as any, showcase: val });
        setPage(1);
        setPageInputValue('1');
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
                description: t('chatConfig.batchDeleteSuccess', { count: selectedItems.length })
            });
        } catch (error) {
            toast({ variant: 'error', description: '删除失败，请稍后重试' });
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
                toast({ variant: 'success', description: t('chatConfig.sopUpdated') });
            } else {
                // 新建操作
                await sopApi.addSop(requestData);
                toast({ variant: 'success', description: t('chatConfig.sopCreated') });
            }

            setIsDrawerOpen(false);
            fetchData({
                page: page,
                pageSize: 10,
                keyword: keywords
            }); // 刷新列表
            resetSopForm(); // 重置表单
        } catch (error) {
        }
    };

    const handleEdit = (id: string) => {
        const sopToEdit = datalist.find(item => item.id === id);
        if (!sopToEdit) {
            toast({ variant: 'warning', description: t('chatConfig.notFoundSop') });
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
            title: t('chatConfig.deleteConfirmTitle'),
            desc: t('chatConfig.deleteConfirmDesc'),
            showClose: true,
            okTxt: t('chatConfig.confirmDelete'),
            canelTxt: t('cancel'),
            onOk(next) {
                sopApi.deleteSop(id)
                    .then(() => {
                        toast({
                            variant: 'success',
                            description: t('chatConfig.deleteSuccess')
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
                        console.error('delete sop failed:', error);
                        toast({
                            variant: 'error',
                            description: t('chatConfig.deleteFailed'),
                            details: error.message || t('chatConfig.requestFailed')
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
    const { getRootProps: getLocalFileRootProps, getInputProps: getLocalFileInputProps } = useDropzone({
        multiple: false,
        accept: {
            // 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.csv'],
            // 'application/*': ['.xlsx'] // 结合扩展名和 MIME 类型双重验证
            "": [".xlsx"],
        },
        useFsAccessApi: false,
        onDrop: (acceptedFiles, rejectedFiles) => {
            // 1. 如果用户上传了不支持的文件（如 .pdf、.docx）
            if (rejectedFiles.length > 0) {
                message({ variant: 'warning', description: t('chatConfig.uploadXlsxTip') });
                return;
            }

            // 2. 如果用户上传了 .xlsx 文件，但文件名可能被篡改（如 fake.xlsx.pdf）
            const file = acceptedFiles[0];
            const ext = file.name.split('.').pop().toLowerCase();
            if (ext !== 'xlsx') {
                message({ variant: 'warning', description: t('chatConfig.fileExtMustBeXlsx') });
                return;
            }
            setImportFiles(acceptedFiles);
        },
    });
    const handleLocalFileImport = async () => {
        setIsImporting(true);
        try {
            const formData = new FormData();
            formData.append('file', importFiles[0]);

            setImportFilesData([importFiles[0]]); // 只保存一个文件
            const res = await sopApi.UploadSopRecord(formData);
            console.log('API Response:', res); // 调试用
            if (res.status_code === 11010) {
                setValidationDialog({
                    open: true,
                    status_message: res.status_message
                });
            }
            if (res.status_code !== 11010) {


                if (res?.repeat_name) {
                    console.log(1111);
                    const formData = new FormData();

                    formData.append('file', importFiles[0]);

                    formData.append('ignore_error', 'false');
                    formData.append('override', 'false');
                    formData.append('save_new', 'false');
                    const res = await sopApi.UploadSopRecord(formData);

                    console.log(res, res?.repeat_name);
                    setImportDialogOpen(true)
                    setDuplicateNames(res?.repeat_name);
                    setDuplicateDialogOpen(true);
                    setImportFormData(formData);
                } else {
                    toast({ variant: 'success', description: t('chatConfig.submitSuccess') });
                    fetchData({
                        page: page,
                        pageSize: pageSize,
                        keyword: keywords
                    });
                }
            }

        } finally {
            setIsImporting(false);
        }
    };
    const handleValidationDialogConfirm = async () => {
        console.log(111);
        const formData = new FormData();
        importFilesData.forEach(file => {
            formData.append('file', file);
        });
        formData.append('ignore_error', 'true');
        formData.append('override', 'false');
        formData.append('save_new', 'false');

        setValidationDialog(prev => ({ ...prev, open: false }));



        const res = await captureAndAlertRequestErrorHoc(sopApi.UploadSopRecord(formData));
        if (res?.repeat_name) {
            setImportDialogOpen(true)
            setDuplicateNames(res.repeat_name);
            setDuplicateDialogOpen(true);
            setImportFormData(formData);
            return
        } else {
            fetchData({
                page: page,
                pageSize: pageSize,
                keyword: keywords
            });
            toast({ variant: 'success', description: t('chatConfig.submitSuccess') });
        }
    };
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
                               label={t('chatConfig.inputPlaceholder')}
                            value={formData.linsightConfig?.input_placeholder}
                            placeholder={t('chatConfig.linsightPlaceholder')}
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
                             <p className="text-lg font-bold mb-2">{t('chatConfig.linsightTools')}</p>
                            <ToolSelectorContainer
                                toolsData={toolsData}
                                selectedTools={selectedTools}
                                toggleTool={toggleTool}
                                removeTool={removeTool}
                                isToolSelected={isToolSelected}
                                handleDragEnd={handleDragEnd}
                                toggleGroup={toggleGroup}
                                activeToolTab={activeToolTab}
                                setActiveToolTab={setActiveToolTab}
                                showToolSelector={showToolSelector}
                                setShowToolSelector={setShowToolSelector}
                                toolSearchTerm={toolSearchTerm}
                                setToolSearchTerm={setToolSearchTerm}
                            />
                        </div>

                        <div className="mb-6">
                            <p className="text-lg font-bold mb-2">{t('chatConfig.linsightManual')}</p>
                            <div className="flex items-center gap-2 mb-2">
                                <div className="relative flex-1 max-w-xs">
                                    <div className="relative">
                                        <input
                                            type="text"
                                             placeholder={t('chatConfig.searchManual')}
                                            className="w-full pl-10 pr-3 py-1.5 text-sm border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                                            value={keywords}
                                            onChange={(e) => {
                                                const newValue = e.target.value;
                                                setKeywords(newValue);
                                                handleSearch(newValue);
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
                                    <Button
                                        variant="default"
                                        size="sm"
                                        onClick={() => { setImportDialogOpen(true); setImportFilesData(null) }}
                                    >
                                        {t('chatConfig.importFromRecord')}
                                    </Button>
                                    <Button
                                        variant="outline"
                                        size="sm"
                                        onClick={() => setLocalFileDialogOpen(true)}
                                    >
                                        {t('chatConfig.importFromLocal')}
                                    </Button>

                                    <Button
                                        variant="outline"
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
                                        {t('chatConfig.createManual')}
                                    </Button>
                                    <Button
                                        variant="outline"
                                        size="sm"
                                        disabled={selectedItems.length === 0 || batchDeleting}
                                        onClick={() => {
                                            bsConfirm({
                                               title: t('chatConfig.batchDeleteConfirm'),
                                            desc: t('chatConfig.batchDeleteDesc'),
                                            showClose: true,
                                            okTxt: t('chatConfig.confirmDelete'),
                                            canelTxt: t('cancel'),
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
                                       {t('chatConfig.batchDelete')}

                                    </Button>
                                </div>
                            </div>
                            <ImportFromRecordsDialog
                                open={importDialogOpen}
                                tools={selectedTools}
                                onOpenChange={setImportDialogOpen}
                                //  onSuccess={refreshSopList}
                                setDuplicateNames={setDuplicateNames}
                                duplicateNames={duplicateNames}
                                duplicateDialogOpen={duplicateDialogOpen}
                                setDuplicateDialogOpen={setDuplicateDialogOpen}
                                importFormData={importFormData}
                            />
                            {/* 表格区域 */}
                            <SopTable datalist={datalist} selectedItems={selectedItems} handleSelectItem={handleSelectItem} handleSelectAll={handleSelectAll} handleSort={handleSort} handleEdit={handleEdit} handleDelete={handleDelete} page={page} pageSize={pageSize} total={total} loading={loading} pageInputValue={pageInputValue} handlePageChange={handlePageChange} handlePageInputChange={handlePageInputChange} handlePageInputConfirm={handlePageInputConfirm} handleKeyDown={handleKeyDown} onShowcaseFilterChange={handleShowcaseFilterChange} />
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
                                            { t('cancel')}
                                            </Button>
                                            <Button
                                                type="button"
                                                onClick={() => {
                                                    deleteConfirmModal.onConfirm();
                                                    setDeleteConfirmModal(prev => ({ ...prev, open: false }));
                                                }}
                                            >
                                               { t('chatConfig.confirmDelete')}
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
                        <Button onClick={() => handleSave(formData)}>{t('save')}</Button>
                    </div>
                </CardContent>
            </Card>
            <Dialog open={localFileDialogOpen} onOpenChange={setLocalFileDialogOpen}>
                <DialogContent className="sm:max-w-[1200px]">
                    <DialogHeader>
                        <DialogTitle>{t('chatConfig.importManual')}</DialogTitle>
                    </DialogHeader>

                    <div className="grid gap-4 py-4">
                        <div className="flex justify-between items-center w-full">
                            <div className="flex items-center gap-2">
                                <span className="text-red-500">*</span>
                                 <span>{t('chatConfig.uploadFile')}</span>
                            </div>
                            <button
                                className="flex items-center gap-1"
                                onClick={() => downloadFile(__APP_ENV__.BASE_URL + "/sopexample.xlsx", t('chatConfig.exampleFileName'))}
                            >
                                <span className="text-black">{t('chatConfig.exampleFile')}:</span>
                                <span className="text-blue-600 hover:underline">{t('chatConfig.exampleFileName')}</span>
                            </button>
                        </div>

                        <div
                            {...getLocalFileRootProps()}
                            className="group h-40 border border-dashed rounded-md flex flex-col justify-center items-center cursor-pointer gap-3 hover:border-primary"
                        >
                            <input {...getLocalFileInputProps()} />
                            <UploadIcon className="group-hover:text-primary size-5" />
                            <p className="text-sm">{t('code.clickOrDragHere')}</p>

                        </div>
                        {importFiles.length > 0 && (
                            <div className="text-sm text-start text-green-500 mt-2">
                                {importFiles.slice(0, 1).map((file, index) => (
                                    <div key={index}>
                                        <span>
                                            {file.name}
                                        </span>
                                        {/* <button 
                        onClick={(e) => {
                            e.stopPropagation();
                            setImportFiles([]); 
                        }}
                        className="text-red-500 hover:text-red-700"
                    >
                        ×
                    </button> */}
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>

                    <div className="flex justify-end gap-2">
                        <Button
                            variant="outline"
                            onClick={() => {
                                setLocalFileDialogOpen(false);
                                setImportFiles([]);
                            }}
                        >
                            {t('cancel')}
                        </Button>
                        <Button
                            onClick={async () => {
                                await handleLocalFileImport(); // 等待导入完成
                                setImportFiles([])
                                setLocalFileDialogOpen(false); // 关闭弹窗
                            }}
                            disabled={isImporting || importFiles.length === 0}
                        >
                              {isImporting ? t('chatConfig.importing') : t('submit')}
                        </Button>
                    </div>
                </DialogContent>
            </Dialog>
            <Dialog open={validationDialog.open} onOpenChange={(open) => setValidationDialog(prev => ({ ...prev, open }))}>
                <DialogContent className="sm:max-w-[500px] max-h-[80vh]" close={false}>
                    {/* 静态蓝色竖条 - 始终显示 */}
                    <div className="absolute left-0 top-0 h-full w-1.5 bg-blue-500"></div>

                    {/* 可滚动区域 - 仅在内容溢出时显示滚动条 */}
                    <div
                        className="pl-4 overflow-y-auto"
                        style={{
                            maxHeight: 'calc(80vh - 2rem)', // 减去padding等空间
                            scrollbarWidth: 'thin',
                            scrollbarColor: '#3b82f6 transparent' // blue-500
                        }}
                    >
                        {/* 自定义滚动条样式 (Webkit浏览器) */}
                        <style jsx>{`
        .overflow-y-auto::-webkit-scrollbar {
          width: 8px;
        }
        .overflow-y-auto::-webkit-scrollbar-track {
          background: transparent;
        }
        .overflow-y-auto::-webkit-scrollbar-thumb {
          background: #3b82f6; /* blue-500 */
          border-radius: 4px;
        }
      `}</style>

                        <DialogHeader>
                            <div className="flex items-center gap-4">
                                <div className="w-8 h-8 rounded-full bg-blue-500 flex items-center justify-center">
                                    <span className="text-white font-bold text-lg">i</span>
                                </div>
                                <DialogTitle>{t('chatConfig.fileFormatError')}</DialogTitle>
                            </div>
                        </DialogHeader>

                        <div className="py-4">
                            {validationDialog.status_message && (
                                <div className="space-y-2">
                                    <p className="font-medium">
                                        {validationDialog.status_message.split("：")[0]}：
                                    </p>
                                    {validationDialog.status_message.includes("：") && (
                                        <div className="text-sm text-gray-600">
                                            {validationDialog.status_message.split("：")[1].split("\n").map((line, index) => (
                                                <p key={index}>{line.trim()}</p>
                                            ))}
                                        </div>
                                    )}
                                </div>
                            )}
                        </div>

                        <div className="flex justify-end">
                            <Button onClick={handleValidationDialogConfirm}>
                                 {t('chatConfig.gotIt')}
                            </Button>
                        </div>
                    </div>
                </DialogContent>
            </Dialog>
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
        console.log(formData, 'formData', selectedTools, 22);

        const processedTools = selectedTools.map(tool => ({
            id: tool.id,
            name: tool.name,
            is_preset: tool.is_preset,
            tool_key: tool.tool_key,
            description: tool.description,
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
                toast({ variant: 'success', description: t('chatConfig.saveSuccess') });
                return true;
            }
        } catch (error) {
            toast({ variant: 'error', description: t('chatConfig.saveFailed') });
            return false;
        }
    };

    return { handleSave };
};

function setTotal(arg0: any) {
    throw new Error("Function not implemented.");
}
