import { useNavigate } from "react-router-dom";
import { Button } from "../../components/bs-ui/button";
import TipPng from "@/assets/Vector.svg";
import { Input, SearchInput } from "../../components/bs-ui/input";
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow
} from "../../components/bs-ui/table";

import { useContext, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Textarea } from "../../components/bs-ui/input";
import { userContext } from "../../contexts/userContext";
import { copyLibDatabase, createFileLib, deleteFileLib, readFileLibDatabase, updateKnowledge } from "../../controllers/API";
import { captureAndAlertRequestErrorHoc } from "../../controllers/request";
import { LoadIcon, LoadingIcon } from "@/components/bs-icons/loading";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { Dialog, DialogClose, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger } from "@/components/bs-ui/select";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { getKnowledgeModelConfig, getLLmServerDetail, getModelListApi } from "@/controllers/API/finetune";
import { CircleAlert, Copy, Ellipsis, LoaderCircle, Settings, Trash2 } from "lucide-react";
import AutoPagination from "../../components/bs-ui/pagination/autoPagination";
import { useTable } from "../../util/hook";
import { ModelSelect } from "../ModelPage/manage/tabs/WorkbenchModel";
import { QuestionTooltip } from "@/components/bs-ui/tooltip";

function CreateModal({ datalist, open, onOpenChange, onLoadEnd, mode = 'create', currentLib = null }) {
    const { t } = useTranslation()
    const navigate = useNavigate()

    const nameRef = useRef(null)
    const descRef = useRef(null)
    const [modal, setModal] = useState(null)
    const [options, setOptions] = useState([])
    const [isSubmitting, setIsSubmitting] = useState(false)
    const [isModelChanged, setIsModelChanged] = useState(false)

    // 统一处理模型数据获取
    useEffect(() => {
        if (!open) return;

        const fetchModelData = async () => {
            try {
                const [config, data] = await Promise.all([getKnowledgeModelConfig(), getModelListApi()]);
                const { embedding_model_id } = config;
                let embeddings = [];
                let models = {};
                let _model = null;

                data.forEach(server => {
                    const serverItem = { value: server.id, label: server.name, children: [] };
                    serverItem.children = server.models.reduce((res, model) => {
                        if (model.model_type !== 'embedding' || !model.online) return res;
                        const modelItem = { value: model.id, label: model.model_name };
                        models[model.id] = server.name + '/' + model.model_name;

                        if (mode === 'edit' && currentLib && model.id === currentLib.model) {
                            _model = [serverItem, modelItem];
                        } else if (mode === 'create' && model.id === embedding_model_id && !_model) {
                            _model = [serverItem, modelItem];
                        }
                        return [...res, modelItem];
                    }, []);

                    if (serverItem.children.length) embeddings.push(serverItem);
                });

                setOptions(embeddings);
                onLoadEnd(models);

                if (mode === 'edit' && currentLib) {
                    if (nameRef.current) nameRef.current.value = currentLib.name;
                    if (descRef.current) descRef.current.value = currentLib.description;
                    setIsModelChanged(false);

                    if (_model) {
                        setModal(_model);
                    } else {
                        try {
                            const res = await getLLmServerDetail(currentLib.model);
                            if (res.data) {
                                setModal(res.data);
                            }
                        } catch (error) {
                            console.warn('Failed to get server detail, using fallback');
                            if (embeddings.length > 0 && embeddings[0].children.length > 0) {
                                setModal([embeddings[0], embeddings[0].children[0]]);
                            }
                        }
                    }
                } else if (mode === 'create' && _model) {
                    setModal(_model);
                }
            } catch (error) {
                console.error('Failed to load model data:', error);
                toast({
                    variant: "error",
                    description: '加载模型出错'
                });
            }
        };

        fetchModelData();
    }, [open, mode, currentLib]);

    const { toast } = useToast()
    const [error, setError] = useState({ name: false, desc: false })

const handleCreate = async (e, isImport = false) => {
  const name = nameRef.current.value || ''; // 名称（默认空字符串，避免null）
  let desc = descRef.current.value || '';   // 描述（默认空字符串）

  // 1. 定义默认描述的“固定文本部分”（不含名称）
  const defaultDescPrefix = "当回答与";
  const defaultDescSuffix = "相关的问题时，参考此知识库";
  // 固定文本总长度 = 前缀长度 + 后缀长度
  const fixedTextLength = defaultDescPrefix.length + defaultDescSuffix.length;
  // 名称可占用的最大长度 = 200 - 固定文本长度（确保名称+固定文本≤200）
  const maxNameLengthForDefaultDesc = 200 - fixedTextLength;

  // 2. 未输入描述时，生成默认描述（严格控制总长度≤200）
  if (!desc) {
    // 情况1：名称长度 ≤ 可占用最大长度 → 直接拼接生成默认描述
    if (name.length <= maxNameLengthForDefaultDesc) {
      desc = `${defaultDescPrefix}${name}${defaultDescSuffix}`;
    } 
    // 情况2：名称长度 > 可占用最大长度 → 截断名称后再拼接
    else {
      // 截断名称（保留前 maxNameLengthForDefaultDesc 个字，避免总长度超200）
      const truncatedName = name.slice(0, maxNameLengthForDefaultDesc);
      // 生成截断后的默认描述
      desc = `${defaultDescPrefix}${truncatedName}${defaultDescSuffix}`;
      // 提示用户：名称过长已被截断（提升体验，避免用户困惑）
      toast({
        variant: "info",
        description: `知识库名称过长，已自动截断为${maxNameLengthForDefaultDesc}字，确保默认描述不超过200字限制`
      });
    }
  }

  // 3. 原有校验逻辑（仅针对用户手动输入的描述，默认描述已确保≤200）
  if (!name) {
    handleError(t('lib.enterLibraryName'));
    return;
  }
  if (name.length > 30) {
    handleError('知识库名称不能超过30字');
    return;
  }
  if (!modal) {
    handleError(t('lib.selectModel'));
    return;
  }
  if (datalist.find(data => data.name === name && (!currentLib || data.id !== currentLib.id))) {
    handleError(t('lib.nameExists'));
    return;
  }
  // 仅校验用户手动输入的描述（默认描述已控制长度，可跳过）
  if (descRef.current.value && desc.length > 200) {
    handleError(t('lib.descriptionLimit'));
    return;
  }

        setIsSubmitting(true)

        if (mode === 'create') {
            await captureAndAlertRequestErrorHoc(createFileLib({
                name,
                description: desc,
                model: modal[1].value,
                type: 0
            }).then(res => {
                window.libname = [name, desc]
                navigate(isImport
                    ? `/filelib/upload/${res.id}`
                    : `/filelib/${res.id}`
                );
                onOpenChange(false); // 修复：用onOpenChange关闭弹窗
            })).finally(() => {
                setIsSubmitting(false)
            })
        } else {
            const data = {
                "model_id": modal[1].value,
                "model_type": "embedding",
                "knowledge_id": currentLib.id,
                "knowledge_name": name,
                "description": desc
            }
            await captureAndAlertRequestErrorHoc(updateKnowledge(data).then(res => {
                toast({
                    variant: "success",
                    description: '更新成功'
                })
                onOpenChange(false); // 修复：用onOpenChange关闭弹窗（替代原setOpen）
                onLoadEnd()
            }).catch(error => {
                toast({ variant: "error", description: '更新失败，请重试' });
                onOpenChange(false); // 错误时也关闭弹窗，避免状态卡住
            })).finally(() => {
                setIsSubmitting(false)
            })
        }
    }

    const handleError = (message) => {
        toast({
            variant: 'error',
            description: message
        });
    }

    return <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="sm:max-w-[625px]">
            <DialogHeader>
                <DialogTitle>{mode === 'create' ? t('lib.createLibrary') : '知识库设置'}</DialogTitle>
            </DialogHeader>
            <div className="flex flex-col gap-4 py-2">
                {mode === 'edit' && currentLib && (
                    <div className="space-y-4">
                        <div className="flex items-center gap-48">
                            <label className="bisheng-label text-sm text-gray-500">{t('lib.knowledgeBaseId')}</label>
                            <div className="text-sm">{currentLib.id}</div>
                        </div>
                        <div className="flex items-center gap-48">
                            <label className="bisheng-label text-sm text-gray-500">{t('createTime')}</label>
                            <div className="text-sm">
                                {currentLib.create_time.replace('T', ' ')}
                            </div>
                        </div>
                    </div>
                )}
                <div className="">
                    <label htmlFor="name" className="bisheng-label">{t('lib.libraryName')}</label>
                    <span className="text-red-500">*</span>
                    <Input
                        name="name"
                        ref={nameRef}
                        defaultValue={mode === 'edit' && currentLib ? currentLib.name : ''}
                        placeholder={t('lib.enterLibraryName')}
                        className={`col-span-3 ${error.name && 'border-red-400'}`}
                    />
                </div>
                <div className="">
                    <label htmlFor="desc" className="bisheng-label">知识库描述</label>
                    <Textarea
                        id="desc"
                        ref={descRef}
                        defaultValue={mode === 'edit' && currentLib ? currentLib.description : ''}
                        placeholder="请输入知识库描述"
                        rows={8}
                        className={`col-span-3 ${error.desc && 'border-red-400'}`}
                    />
                </div>
                <div className="">
                    <label htmlFor="model" className="bisheng-label">知识库embedding模型选择</label>
                    {options.length > 0 && (
                        <ModelSelect
                            close
                            value={modal ? modal[1]?.value : (mode === 'edit' && currentLib ? currentLib.model : null)}
                            options={options}
                            onChange={(modelId) => {
                                let serverItem = null;
                                let modelItem = null;
                                options.forEach(server => {
                                    const foundModel = server.children?.find(child => child.value == modelId);
                                    if (foundModel) {
                                        serverItem = { value: server.value, label: server.label };
                                        modelItem = foundModel;
                                    }
                                });

                                if (serverItem && modelItem) {
                                    setModal([serverItem, modelItem]);
                                    if (mode === 'edit') setIsModelChanged(true);
                                }
                            }}
                        />
                    )}
                    {mode === 'edit' && isModelChanged && (
                        <p className="text-red-500 text-sm mt-1 flex items-center gap-1">
                            <CircleAlert className="w-4 h-4" color="#ef4444" />
                            修改 embedding 模型可能会消耗大量模型资源且耗时较久，请谨慎进行
                        </p>
                    )}
                </div>
            </div>
            <DialogFooter>
                <DialogClose>
                    <Button variant="outline" className="px-8 h-8">{t('cancel')}</Button>
                </DialogClose>
                {mode === 'create' ? (
                    <>
                        <Button
                            variant="outline"
                            className="px-8 h-8 flex"
                            onClick={(e) => handleCreate(e, false)}
                            disabled={isSubmitting}
                        >
                            {isSubmitting && <LoadIcon className="mr-1" />}
                            完成创建
                        </Button>
                        <Button
                            type="submit"
                            className="px-8 h-8 flex"
                            onClick={(e) => handleCreate(e, true)}
                            disabled={isSubmitting}
                        >
                            {isSubmitting && <LoadIcon className="mr-1" />}
                            {t('createImport')}
                        </Button>
                    </>
                ) : (
                    <Button
                        type="submit"
                        className="px-8 h-8 flex"
                        onClick={(e) => handleCreate(e, false)}
                        disabled={isSubmitting}
                    >
                        {isSubmitting && <LoadIcon className="mr-1" />}
                        {t('confirm')}
                    </Button>
                )}
            </DialogFooter>
        </DialogContent>
    </Dialog>
}

const doing = {} // 记录copy中的知识库
export default function KnowledgeFile() {
    const [open, setOpen] = useState(false);
    const { user } = useContext(userContext);
    const { message } = useToast()
    const navigate = useNavigate()
    const [settingsOpen, setSettingsOpen] = useState(false);
    const [currentSettingLib, setCurrentSettingLib] = useState(null);
    const [copyLoadingId, setCopyLoadingId] = useState<string | null>(null);
    // 新增：控制Select下拉状态，避免偶发不弹出
    const [selectOpenId, setSelectOpenId] = useState<string | null>(null);
const [forceRender, setForceRender] = useState(0);
  const triggerForceRender = () => setForceRender(prev => prev + 1);
    const { page, pageSize, data: datalist, total, loading, setPage, search, reload } = useTable({ cancelLoadingWhenReload: true }, (param) =>
        readFileLibDatabase({ ...param, name: param.keyword })
    )

    // 复制中开启轮询
   useEffect(() => {
        const todos = datalist.reduce((prev, curr) => {
            if (curr.state === 1) {
                prev.push({ id: curr.id, name: curr.name })
            }
            return prev
        }, [])

        todos.map(todo => {
            if (doing[todo.id]) {
                const lib = datalist.find(item => item.id === todo.id);
                if (lib && lib.state !== 1) {
                    message({
                        variant: 'success',
                        description: `${todo.name} 复制完成`
                    })
                    delete doing[todo.id]
                }
            }
        })

        if (todos.length > 0) {
            setTimeout(() => {
                reload()
            }, 5000);
        }
    }, [datalist])


    const handleDelete = (id) => {
        bsConfirm({
            title: t('prompt'),
            desc: t('lib.confirmDeleteLibrary'),
            onOk(next) {
                captureAndAlertRequestErrorHoc(deleteFileLib(id).then(res => {
                    reload();
                }));
                next()
            },
        })
    }
        const handleOpenSettings = (lib) => {
        if (!settingsOpen && lib?.id) {
            setCurrentSettingLib(lib);
            setSettingsOpen(true);
            setSelectOpenId(null); // 打开弹窗前先关闭下拉
            triggerForceRender(); // 强制组件重绘，避免状态延迟
        }
    }
    const handleSettingsClose = (isOpen) => {
        setSettingsOpen(isOpen);
        if (!isOpen) {
            setCurrentSettingLib(null); // 清空当前编辑的库
            setSelectOpenId(null); // 关闭下拉菜单
            // 延迟100ms确保状态同步到DOM，避免下次点击时状态残留
            setTimeout(() => triggerForceRender(), 100);
        }
    }
    // 进详情页前缓存 page, 临时方案
    const handleCachePage = () => {
        window.LibPage = { page, type: 'file' }
    }
    useEffect(() => {
        const _page = window.LibPage
        if (_page) {
            setPage(_page.page);
            delete window.LibPage
        } else {
            setPage(1);
        }
    }, [])

    const { t, i18n } = useTranslation();
    useEffect(() => {
        i18n.loadNamespaces('knowledge');
    }, [i18n]);

    // copy
    const handleCopy = async (elem) => {
        const newName = `${elem.name}的副本`;
        if (newName.length > 200) {
            message({
                variant: 'error',
                description: '复制失败：复制后的知识库名称超过200字限制'
            });
            return;
        }
        setCopyLoadingId(elem.id);
        doing[elem.id] = true;
        try {
            await captureAndAlertRequestErrorHoc(copyLibDatabase(elem.id));
            reload();
        } catch (error) {
            message({
                variant: 'error',
                description: '复制失败'
            });
        } finally {
            setCopyLoadingId(null);
        }
    }

    useEffect(() => {
        console.log("settingsOpen 状态变化：", settingsOpen);
    }, [settingsOpen]);

    return (
        <div className="relative">
            {loading && <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
                <LoadingIcon />
            </div>}
            <div className="h-[calc(100vh-128px)] overflow-y-auto pb-20">
                <div className="flex justify-end gap-4 items-center absolute right-0 top-[-44px]">
                    <SearchInput placeholder={t('lib.searchPlaceholder')} onChange={(e) => search(e.target.value)} />
                    <Button className="px-8 text-[#FFFFFF]" onClick={() => setOpen(true)}>{t('create')}</Button>
                </div>
                <Table>
                    <TableHeader>
                        <TableRow>
                            <TableHead>{t('lib.libraryName')}</TableHead>
                            <TableHead>{t('updateTime')}</TableHead>
                            <TableHead>{t('lib.createUser')}</TableHead>
                            <TableHead className="text-right">{t('operations')}</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {datalist.map((el: any) => (
                            <TableRow
                                key={el.id}
                                // 移除：原行点击事件，移到内容列单独绑定
                            >
                                {/* 名称列：单独绑定跳转事件 */}
                                <TableCell 
                                    className="font-medium max-w-[200px]"
                                    onClick={() => {
                                        window.libname = [el.name, el.description];
                                        navigate(`/filelib/${el.id}`);
                                        handleCachePage();
                                    }}
                                >
                                    <div className="flex items-center gap-2 py-2">
                                        <div className="w-[50px] h-[50px]">
                                            <img src={TipPng} alt="" />
                                        </div>
                                        <div>
                                            <div className="truncate max-w-[500px] w-[264px] text-[18px] font-medium pt-2 flex items-center gap-2">
                                                {el.name}
                                            </div>
                                            <QuestionTooltip
                                                content={el.description || ''} 
                                                error={false}
                                                className="w-full text-start"
                                            >
                                                <div className="truncate max-w-[300px] text-[14px] text-[#5A5A5A] pt-1">
                                                    {el.description || ''} 
                                                </div>
                                            </QuestionTooltip>
                                        </div>
                                    </div>
                                </TableCell>

                                {/* 更新时间列：单独绑定跳转事件 */}
                                <TableCell 
                                    className="text-[#5A5A5A]"
                                    onClick={() => {
                                        window.libname = [el.name, el.description];
                                        navigate(`/filelib/${el.id}`);
                                        handleCachePage();
                                    }}
                                >
                                    {el.update_time.replace('T', ' ')}
                                </TableCell>

                                {/* 创建用户列：单独绑定跳转事件 */}
                                <TableCell 
                                    className="max-w-[300px] break-all"
                                    onClick={() => {
                                        window.libname = [el.name, el.description];
                                        navigate(`/filelib/${el.id}`);
                                        handleCachePage();
                                    }}
                                >
                                    <div className="truncate-multiline text-[#5A5A5A]">{el.user_name || '--'}</div>
                                </TableCell>

                    {/* 操作列：修复Select的事件逻辑 */}
<TableCell className="text-right">
  <div className="flex items-center justify-end gap-2">
    <Select
      open={selectOpenId === el.id}
      onOpenChange={(isOpen) => {
        setSelectOpenId(isOpen ? el.id : null);
      }}
      onValueChange={(selectedValue) => {
        setSelectOpenId(null); // 点击后关闭下拉
        // 1. 打印日志（现在会正常触发）
        console.log("选中的选项值：", selectedValue, "当前知识库ID：", el.id, "settingsOpen状态：", settingsOpen);
        
        // 2. 根据选中的值分情况处理
        switch (selectedValue) {
          case 'copy':
            el.state === 1 && handleCopy(el);
            break;
          case 'set': // 处理“设置”选项
            if (!settingsOpen && el?.id) {
              setCurrentSettingLib(el);
              setSettingsOpen(true);
            }
            break;
          case 'delete':
            el.copiable && handleDelete(el.id);
            break;
        }
      }}
    >
      <SelectTrigger
        showIcon={false}
        disabled={copyLoadingId === el.id}
        onClick={(e) => {
          e.stopPropagation(); // 阻止冒泡到表格行
        }}
        className="size-10 px-2 bg-transparent border-none shadow-none hover:bg-gray-300 flex items-center justify-center duration-200 relative"
      >
        {copyLoadingId === el.id ? (
          <>
            <LoaderCircle className="animate-spin" />
            <div className="absolute -top-8 left-1/2 transform -translate-x-1/2 bg-white text-gray-800 text-xs px-2 py-1 rounded whitespace-nowrap border border-gray-300 shadow-sm">
              复制中
            </div>
          </>
        ) : (
          <Ellipsis size={24} color="#a69ba2" strokeWidth={1.75} />
        )}
      </SelectTrigger>
      <SelectContent 
        onClick={(e) => {
          e.stopPropagation(); // 阻止冒泡到外部
        }}
        className="z-50"
      >
        {/* 复制选项 */}
        {(el.copiable || user.role === 'admin') && (
          <SelectItem
            showIcon={false}
            value="copy"
             disabled={el.state !== 1 || copyLoadingId === el.id}
          >
            <div className="flex gap-2 items-center">
              <Copy className="w-4 h-4" />
              { t('lib.copy') }
            </div>
          </SelectItem>
        )}
        {/* 设置选项：删除onClick，仅保留value和内容 */}
        <SelectItem 
          value="set" 
          showIcon={false}
          
        >
          <div className="flex gap-2 items-center">
            <Settings className="w-4 h-4" />
            {t('设置')}
          </div>
        </SelectItem>
        {/* 删除选项 */}
        <SelectItem
          value="delete"
          showIcon={false}
          disabled={!el.copiable}
        >
          <div className="flex gap-2 items-center">
            <Trash2 className="w-4 h-4" />
            {t('delete')}
          </div>
        </SelectItem>
      </SelectContent>
    </Select>
  </div>
</TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
            </div>
            <div className="bisheng-table-footer px-6 bg-background-login">
                <p className="desc">{t('lib.libraryCollection')}</p>
                <div>
                    <AutoPagination
                        page={page}
                        pageSize={pageSize}
                        total={total}
                        onChange={(newPage) => setPage(newPage)}
                    />
                </div>
            </div>
            {/* 创建弹窗 */}
            <CreateModal
                datalist={datalist}
                open={open}
                onOpenChange={setOpen}
                onLoadEnd={() => { }}
                mode="create"
            />
            {/* 编辑（设置）弹窗 */}
            <CreateModal
                datalist={datalist}
                open={settingsOpen}
                onOpenChange={(isOpen) => {
                    setSettingsOpen(isOpen);
                    if (!isOpen) {
                        setCurrentSettingLib(null);
                    }
                }}
                onLoadEnd={reload}
                mode="edit"
                currentLib={currentSettingLib}
            />
        </div>
    );
}