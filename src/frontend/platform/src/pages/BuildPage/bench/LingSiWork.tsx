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
import { useDebounce } from "@/util/hook";
import SopSearchBar from "@/components/LinSight/SopSearchBar";
import SopActionsBar from "@/components/LinSight/SopActionsBar";
import DeleteConfirmModal from "@/components/LinSight/DeleteConfirmModal";
import LocalFileImportDialog from "@/components/LinSight/LocalFileImportDialog";
import ValidationDialog from "@/components/LinSight/ValidationDialog";

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
    const [initialized, setInitialized] = useState(false);
    const [importDialogOpen, setImportDialogOpen] = useState(false);
    const [localFileDialogOpen, setLocalFileDialogOpen] = useState(false);
    const [importFiles, setImportFiles] = useState<File[]>([]);
    const [isImporting, setIsImporting] = useState(false);
    const [validationDialog, setValidationDialog] = useState({
        open: false,
        status_message: "共计划导入0条SOP，格式正确0条，错误0条"
    });
    const [importFilesData, setImportFilesData] = useState<File[]>([]);
    const [duplicateNames, setDuplicateNames] = useState<string[]>([]);
    const [duplicateDialogOpen, setDuplicateDialogOpen] = useState(false);
    const [sopShowcase, setSopShowcase] = useState(false);
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
    // 简单深比较（JSON序列化），用于避免父子相互 set 导致的循环刷新
    const isDeepEqual = (a: any, b: any) => {
        try {
            return JSON.stringify(a) === JSON.stringify(b);
        } catch {
            return a === b;
        }
    };

    useEffect(() => {
        if (parentFormData && !isDeepEqual(formData, parentFormData)) {
            setFormData(parentFormData);
        }
        if (parentFormData?.linsightConfig?.tools) {
            setSelectedTools(parentFormData.linsightConfig.tools);
        }
    }, [parentFormData]);

    useEffect(() => {
        if (parentSetFormData && !isDeepEqual(formData, parentFormData)) {
            parentSetFormData(formData);
        }
    }, [formData, parentFormData]);
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
        fetchData({ page: 1, pageSize: 10, keyword: '', showcase: showcaseFilter });
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
        selectedTools,
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
            pageSize,
            showcase: showcaseFilter
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
                keyword: keywords,
                page,
                pageSize,
                showcase: showcaseFilter
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
                keyword: keywords,
                pageSize,
                showcase: showcaseFilter
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
            showcase: showcaseFilter,
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
      // 使用自定义防抖 hook（500ms，非立即）
      const debouncedCallback = useCallback((value: string) => {
        handleSearch(value, true);
    }, [showcaseFilter]);
    const debouncedSearch = useDebounce(debouncedCallback, 500, false);
    // 仅在卸载时取消，避免因依赖变化反复取消
    useEffect(() => {
        return () => {
            (debouncedSearch as any)?.cancel?.();
        }
    }, []);

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
                showcase: showcaseFilter,
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
        rating: 0,
        showcase: false
    });

    const resetSopForm = () => {
        setSopForm({
            id: '',
            name: '',
            description: '',
            content: '',
            rating: 0,
            showcase: false
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
                keyword: keywords,
                showcase: showcaseFilter
            }); // 刷新列表
            resetSopForm(); // 重置表单
        } catch (error) {
        }
    };

    const [linsight, setLinsight] = useState({});
    const handleEdit = async (id: string) => {
        const sopToEdit = datalist.find(item => item.id === id);
        const res =  await sopApi.getSopShowcaseDetail({ sop_id: id });
        // 根据是否有运行结果设置sopShowcase状态
        setSopShowcase(res.execute_tasks.length === 0);

        setLinsight({ ...res.version_info, tasks: res.execute_tasks });
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
            rating: sopToEdit.rating || 0,
            showcase: sopToEdit.showcase || false  // 添加精选状态
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
                                showcase: showcaseFilter,
                            });
                        } else {
                            fetchData({
                                page: page,
                                pageSize: pageSize,
                                keyword: keywords,
                                showcase: showcaseFilter,
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
                        keyword: keywords,
                        showcase: showcaseFilter
                    });
                }
            }

        } finally {
            setIsImporting(false);
        }
    };
    const handleValidationDialogConfirm = async () => {
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
                keyword: keywords,
                showcase: showcaseFilter
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
                                <SopSearchBar
                                    value={keywords}
                                    placeholder={t('chatConfig.searchManual')}
                                    onChangeValue={setKeywords}
                                    onSearch={(v) => handleSearch(v)}
                                    debounceMs={500}
                                    debounceKey={showcaseFilter}
                                />
                                <SopActionsBar
                                    importFromRecord={() => { setImportDialogOpen(true); setImportFilesData(null) }}
                                    importFromLocal={() => setLocalFileDialogOpen(true)}
                                    createManual={() => {
                                        setIsEditing(false);
                                        setCurrentSopId(null);
                                        setSopShowcase(true);
                                        setSopForm({ id: '', name: '', description: '', content: '', rating: 0, showcase: false });
                                        setIsDrawerOpen(true);
                                    }}
                                    batchDelete={() => {
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
                                            onCancel() { }
                                        });
                                    }}
                                    batchDeleting={batchDeleting}
                                    disableBatchDelete={selectedItems.length === 0}
                                    importText={t('chatConfig.importFromRecord')}
                                    importLocalText={t('chatConfig.importFromLocal')}
                                    createText={t('chatConfig.createManual')}
                                    batchDeleteText={t('chatConfig.batchDelete')}
                                />
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
                            <DeleteConfirmModal
                                open={deleteConfirmModal.open}
                                content={deleteConfirmModal.content}
                                cancelText={t('cancel')}
                                okText={t('chatConfig.confirmDelete')}
                                onClose={() => setDeleteConfirmModal(prev => ({ ...prev, open: false }))}
                                onConfirm={() => { deleteConfirmModal.onConfirm(); setDeleteConfirmModal(prev => ({ ...prev, open: false })); }}
                            />
                            <SopFormDrawer
                                isDrawerOpen={isDrawerOpen}
                                setIsDrawerOpen={setIsDrawerOpen}
                                isEditing={isEditing}
                                sopForm={sopForm}
                                linsight={linsight}
                                setSopForm={setSopForm}
                                handleSaveSOP={handleSaveSOP}
                                tools={selectedTools}
                                sopShowcase={sopShowcase}
                                onShowcaseToggled={() =>
                                    fetchData({
                                        page: page,
                                        pageSize: pageSize,
                                        keyword: keywords,
                                        showcase: showcaseFilter
                                    })
                                }
                            />
                        </div>
                    </div>
                    <div className="flex justify-end gap-4 absolute bottom-1 right-4">
                        <Preview onBeforView={() => handleSave(formData)} />
                        <Button onClick={() => handleSave(formData)}>{t('save')}</Button>
                    </div>
                </CardContent>
            </Card>
            <LocalFileImportDialog
                open={localFileDialogOpen}
                onOpenChange={setLocalFileDialogOpen}
                t={t}
                getRootProps={getLocalFileRootProps}
                getInputProps={getLocalFileInputProps}
                importFiles={importFiles}
                isImporting={isImporting}
                onImport={async () => { await handleLocalFileImport(); setImportFiles([]); setLocalFileDialogOpen(false); }}
                onCancel={() => { setLocalFileDialogOpen(false); setImportFiles([]); }}
                downloadExample={() => downloadFile(__APP_ENV__.BASE_URL + "/sopexample.xlsx", t('chatConfig.exampleFileName'))}
            />
            <ValidationDialog
                open={validationDialog.open}
                statusMessage={validationDialog.status_message}
                t={t}
                onConfirm={handleValidationDialogConfirm}
                onOpenChange={(open) => setValidationDialog(prev => ({ ...prev, open }))}
            />
        </div>
    );
}




const useChatConfig = (
    selectedTools: Array<{ id: string | number; name: string }>,
    setFormData: React.Dispatch<React.SetStateAction<ChatConfigForm>>,
) => {
    const { toast } = useToast();

    const handleSave = async (formData: ChatConfigForm) => {
        // 保留所有必要的字段
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
            // 应用中心欢迎语/描述：若未提供，使用多语言占位默认值
            applicationCenterWelcomeMessage: (formData.applicationCenterWelcomeMessage?.trim?.() || t('chatConfig.appCenterWelcomePlaceholder')),
            applicationCenterDescription: (formData.applicationCenterDescription?.trim?.() || t('chatConfig.appCenterDescriptionPlaceholder')),
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
