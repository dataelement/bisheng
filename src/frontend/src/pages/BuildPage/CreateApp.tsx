import { AssistantIcon } from "@/components/bs-icons";
import { LoadIcon } from "@/components/bs-icons/loading";
import { Accordion } from "@/components/bs-ui/accordion";
import { Button } from "@/components/bs-ui/button";
import { Dialog, DialogClose, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { Input, Textarea } from "@/components/bs-ui/input";
import Avator from "@/components/bs-ui/input/avator";
import { generateUUID } from "@/components/bs-ui/utils";
import AssistantSetting from "@/components/Pro/security/AssistantSetting";
import { locationContext } from "@/contexts/locationContext";
import { createAssistantsApi } from "@/controllers/API/assistant"; // 假设有对应的接口
import { createWorkflowApi } from "@/controllers/API/workflow";
// import { createWorkflowApi, getWorkflowApi, updateWorkflowApi } from "@/controllers/API/workflow"; // 假设有对应的接口
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { uploadFileWithProgress } from "@/modals/UploadModal/upload";
import { AppType } from "@/types/app";
import { forwardRef, useContext, useImperativeHandle, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

type ModalProps = {};
type ModalRef = {
    open: (type: string, id?: number) => void;
    edit: (type: string, appId: string) => void;
};

const CreateApp = forwardRef<ModalRef, ModalProps>(({ onSave }, ref) => {
    const [open, setOpen] = useState(false);
    const [formData, setFormData] = useState({
        url: '',
        name: '',
        desc: '',
    });
    const [appType, setType] = useState<AppType>(AppType.ASSISTANT); // 判断是助手还是工作流
    const [isEditMode, setIsEditMode] = useState(false); // 区分编辑模式
    const [loading, setLoading] = useState(false);
    const { t } = useTranslation();
    const { appConfig } = useContext(locationContext)

    // 应用id (edit)
    const appidRef = useRef<string>('');
    // State for errors
    const [errors, setErrors] = useState<any>({});

    useImperativeHandle(ref, () => ({
        // create
        open(type: AppType, tempId?: number) {
            setType(type);
            setIsEditMode(false);
            setFormData({
                url: '',
                name: '',
                desc: AppType.ASSISTANT === type ? `${t('build.example')}：
${t('build.exampleOne')}
${t('build.exampleTwo')}
1. XX
2. XX
3. …` : '',
            });
            if (tempId) {
                handleSelectTemplate(type, tempId);
            }
            setErrors({})
            setOpen(true);
            tempDataRef.current = null;
            appidRef.current = '';
        },
        // edit
        edit(type: AppType, flow: any) {
            setType(type);
            setIsEditMode(true);
            fetchDetails(type, flow);
            setErrors({})
            setOpen(true);
            tempDataRef.current = null;
            appidRef.current = flow.flow_id;
        },
    }));

    // 从模板中选择
    const tempDataRef = useRef<any>(null);
    const handleSelectTemplate = (type: AppType, tempId: number) => {
        // const tempInfo = type === AppType.ASSISTANT ? ApiAccess() : ApiAccess();
        tempDataRef.current = {}; // template data
        setFormData({
            url: ``,
            name: `tempInfo.name-${generateUUID(5)}`,
            desc: 'tempInfo.desc',
        });
    }

    // 根据 type 和 id 获取详情（编辑模式）
    const fetchDetails = async (type: AppType, flow: any) => {
        setFormData({
            url: flow.logo,
            name: flow.name,
            desc: flow.description,
        });
    };

    // Validate form fields
    const validateField = (name: string, value: string) => {
        switch (name) {
            case 'name':
                if (!value) return AppType.ASSISTANT === appType ? `请填写助手名称` : '请填写工作流名称';
                if (value.length > 50) return AppType.ASSISTANT === appType ? '名称最多50个字符' : '工作流名称不可超过 50 字';
                return '';
            case 'desc':
                if (AppType.ASSISTANT === appType && value.length < 20) return '为了更好的助手效果，描述需要大于20 个字';
                if (AppType.FLOW === appType && value.length > 200) return '工作流描述不可超过 200 字';
                return '';
            default:
                return '';
        }
    };

    // Handle field change
    const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
        const { name, value } = e.target;
        const error = validateField(name, value);
        setFormData(prev => ({ ...prev, [name]: value }));
        setErrors(prev => ({ ...prev, [name]: error }));
    };

    // Validate entire form
    const validateForm = () => {
        const formErrors: any = {};
        let isValid = true;

        Object.keys(formData).forEach(key => {
            const error = validateField(key, formData[key]);
            if (error) {
                formErrors[key] = error;
                isValid = false;
            }
        });

        setErrors(formErrors);
        return isValid;
    };

    // Handle form submission
    const navigate = useNavigate()
    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        const isValid = validateForm();
        if (!isValid) return;

        setLoading(true);
        if (isEditMode) {
            // 编辑
            setLoading(false);
            setOpen(false);
            // 修改成功
            return onSave({
                name: formData.name,
                description: formData.desc,
                logo: formData.url
            })
        }

        // let res = null
        if (tempDataRef.current) {
            // 模板创建
            console.log('模板创建 :>> ');
            // tempDataRef.current + formData
            // await captureAndAlertRequestErrorHoc(createAssistantApi(formData.name, formData.desc, formData.url));
        } else {
            // 创建
            if (appType === AppType.ASSISTANT) {
                const res = await captureAndAlertRequestErrorHoc(createAssistantsApi(formData.name, formData.desc, formData.url))
                if (res) {
                    //@ts-ignore
                    window.assistantCreate = true // 标记新建助手
                    navigate('/assistant/' + res.id)
                }
            } else {
                // 工作流
                const res = await captureAndAlertRequestErrorHoc(createWorkflowApi(formData.name, formData.desc, formData.url))
                if (res) navigate('/flow/' + res.id)
            }
        }
        setLoading(false);
    };

    // 上传头像逻辑
    const uploadAvator = (file: File) => {
        uploadFileWithProgress(file, (progress) => { }, 'icon').then(res => {
            setFormData(prev => ({ ...prev, url: res.file_path }));
        });
    };

    return (
        <Dialog open={open} onOpenChange={setOpen}>
            <DialogContent className="sm:max-w-[625px] bg-background-login">
                <DialogHeader>
                    <DialogTitle>{isEditMode ? '编辑' : '创建'}{appType === AppType.ASSISTANT ? '助手' : '工作流'}</DialogTitle>
                </DialogHeader>
                <div className="flex flex-col mt-2">
                    <div className="mb-6">
                        <label htmlFor="name" className="bisheng-label">{appType === AppType.ASSISTANT ? '助手头像' : '工作流头像'}</label>
                        <Avator value={formData.url} className="mt-3" onChange={uploadAvator}>
                            <AssistantIcon className="bg-primary w-8 h-8 rounded-sm" />
                        </Avator>
                    </div>
                    <div className="mb-6">
                        <label htmlFor="name" className="bisheng-label">
                            {appType === AppType.ASSISTANT ? t('build.assistantName') : '名称'}
                            <span className="bisheng-tip">*</span>
                        </label>
                        <Input
                            id="name"
                            name="name"
                            maxLength={50}
                            placeholder={appType === AppType.ASSISTANT ? '给助手起个名字' : '给工作流起个名字'}
                            className="mt-3"
                            value={formData.name}
                            onChange={handleChange}
                        />
                        {errors.name && <p className="bisheng-tip mt-1">{errors.name}</p>}
                    </div>
                    <div className="mb-6">
                        <label htmlFor="desc" className="bisheng-label">{appType === AppType.ASSISTANT ? '你希望助手的角色是什么，具体完成什么任务？' : '描述'}</label>
                        <Textarea
                            id="desc"
                            name="desc"
                            placeholder={appType === AppType.ASSISTANT ? t('build.forExample') : '输入工作流描述'}
                            maxLength={appType === AppType.ASSISTANT ? 1000 : undefined}
                            className="mt-3 min-h-32"
                            value={formData.desc}
                            onChange={handleChange}
                        />
                        {errors.desc && <p className="bisheng-tip mt-1">{errors.desc}</p>}
                    </div>
                </div>
                {/* 工作流安全审查 */}
                {appConfig.isPro && <Accordion type="multiple" className="w-full">
                    <AssistantSetting id={'xxx'} type={3} />
                </Accordion>}
                <DialogFooter>
                    <DialogClose>
                        <Button variant="outline" className="px-11" type="button" onClick={() => setFormData({ name: '', desc: '', url: '' })}>
                            {t('cancel')}
                        </Button>
                    </DialogClose>
                    <Button disabled={loading} type="submit" className="px-11" onClick={handleSubmit}>
                        {loading && <LoadIcon className="mr-2" />}
                        {t(isEditMode ? '保存' : '创建')}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
});

export default CreateApp;
