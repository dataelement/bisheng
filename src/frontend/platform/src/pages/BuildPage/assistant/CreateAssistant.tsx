// @ts-strict-ignore
import { Button, Input, Textarea } from '@bisheng/ui';
import { Outlined } from "bisheng-icons";

import Avator from "@/components/bs-ui/input/avator";
import { uploadFileWithProgress } from "@/modals/UploadModal/upload";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";


import { DialogClose,DialogContent,DialogFooter,DialogHeader,DialogTitle } from "../../../components/bs-ui/dialog";

import { createAssistantsApi } from "../../../controllers/API/assistant";
import { captureAndAlertRequestErrorHoc } from "../../../controllers/request";

export default function CreateAssistant() {

    const { t } = useTranslation()

    const [formData, setFormData] = useState<{
        url: string;
        name: string;
        roleAndTasks: string;
    }>({
        url: '',
        name: '',
        roleAndTasks: `${t('build.example')}：
${t('build.exampleOne')}
${t('build.exampleTwo')}
1. XX
2. XX
3. …`,
    });

    const [loading, setLoading] = useState(false);
    // State for errors
    const [errors, setErrors] = useState<any>({});

    // Validate form fields
    const validateField = (name, value) => {
        switch (name) {
            case 'name':
                if (!value) return t('build.nameRequired');
                if (value.length > 50) return t('build.nameMaxLength');
                return '';
            case 'roleAndTasks':
                if (value.length < 20) return t('build.forBetter');
                if (value.length > 1000) return t('build.descMaxLength');
                return '';
            default:
                return '';
        }
    };

    // Handle field change
    const handleChange = (e) => {
        const { name, value } = e.target;
        const error = validateField(name, value);

        setFormData(prev => ({ ...prev, [name]: value }));
        setErrors(prev => ({ ...prev, [name]: error }));
    };

    // Validate entire form
    const validateForm = () => {
        const formErrors = {};
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
    const handleSubmit = async (e) => {
        if ((String((formData.name) ?? '').length > 50) || (String((formData.roleAndTasks) ?? '').length > 1000)) return;

        e.preventDefault();
        const isValid = validateForm();

        if (isValid) {
            console.log('Form data:', formData);
            setLoading(true)
            const res = await captureAndAlertRequestErrorHoc(
                createAssistantsApi(
                    formData.name, formData.roleAndTasks, formData.url,
                ),
            )
            if (res) {
                //@ts-ignore
                window.assistantCreate = true // Mark as creating new assistant
                navigate('/assistant/' + res.id)
            }
            setLoading(false)
        }
    };

    const uploadAvator = (file) => {
        uploadFileWithProgress(file, (progress) => { }, 'icon').then(res => {
            setFormData(prev => ({ ...prev, url: res.relative_path }));
        })
    }

    return <DialogContent className="sm:max-w-[625px] bg-background-login">
        <DialogHeader>
            <DialogTitle>{t('build.establishAssistant')}</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-8 py-6">
            <div className="">
                <label htmlFor="name" className="bisheng-label">{t('build.assistantAvatar')}</label>
                <Avator value={formData.url} className="mt-2" onChange={uploadAvator}><Outlined.Application className="bg-primary w-9 h-9 rounded-sm" /></Avator>
                {/* {errors.name && <p className="bisheng-tip mt-1">{errors.name}</p>} */}
            </div>
            <div className="">
                <label htmlFor="name" className="bisheng-label">{t('build.assistantName')}<span className="bisheng-tip">*</span></label>
                <Input id="name" name="name" maxLength={50} showCount placeholder={t('build.giveAssistantName')} value={formData.name} onChange={handleChange} className={"mt-2"} />
                {errors.name && <p className="bisheng-tip mt-1">{errors.name}</p>}
            </div>
            <div className="">
                <label htmlFor="roleAndTasks" className="bisheng-label">{t('build.whatWant')}</label>
                <Textarea id="roleAndTasks" name="roleAndTasks" placeholder={t('build.forExample')} maxLength={1000} value={formData.roleAndTasks} onChange={handleChange} textareaClassName={"mt-2 min-h-32"} showCount />
                {errors.roleAndTasks && <p className="bisheng-tip mt-1">{errors.roleAndTasks}</p>}
            </div>
        </div>
        <DialogFooter>
            <DialogClose>
                <Button variant="outlined" className="px-11" type="button" onClick={() => setFormData({ url: '', name: '', roleAndTasks: '' })} color="default">{t('cancle')}</Button>
            </DialogClose>
            <Button disabled={((String((formData.name) ?? '').length > 50) || (String((formData.roleAndTasks) ?? '').length > 1000)) || (loading)} type="submit" className="px-11" onClick={handleSubmit}>
                {loading && <Outlined.Loading className="animate-spin mr-2" />}
                {t('build.create')}</Button>
        </DialogFooter>
    </DialogContent>
};
