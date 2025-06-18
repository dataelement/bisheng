import { useContext, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { AssistantIcon } from "@/components/bs-icons";
import { Button } from "@/components/bs-ui/button";
import { DialogClose, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { Input, Textarea } from "@/components/bs-ui/input";
import Avator from "@/components/bs-ui/input/avator";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { locationContext } from "@/contexts/locationContext";
import { getCommitmentApi, setCommitmentApi } from "@/controllers/API";
import { uploadFileWithProgress } from "@/modals/UploadModal/upload";
import { SelectCommitment } from "@/pages/ChatAppPage/components/CommitmentDialog";

// TODO 合并到createapp组件
export default function EditAssistantDialog({ id, logo, online, name, desc, onSave }) {

    const { appConfig } = useContext(locationContext)
    const { t } = useTranslation()
    // State for form fields
    const [formData, setFormData] = useState({ logo: '', name: '', desc: '' });
    // 承诺书id
    const [commitmentId, setCommitmentId] = useState<string>('');

    useEffect(() => {
        setFormData({ logo, name, desc })
        // 承诺书
        if (appConfig.securityCommitment) {
            getCommitmentApi(id).then(res => {
                setCommitmentId(res.length ? res[0].promise_id : '');
            })
        }
    }, [logo, name, desc])
    // console.log(formData, name, desc);

    // State for errors
    const [errors, setErrors] = useState<any>({});

    // Validate form fields
    const validateField = (name, value) => {
        switch (name) {
            case 'name':
                if (!value) return t('build.nameRequired');
                if (value.length > 50) return t('build.nameMaxLength');
                return '';
            case 'desc':
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

    const { message, toast } = useToast()
    // Handle form submission
    const handleSubmit = (e) => {
        e.preventDefault();
        const isValid = validateForm();
        // console.log('Form data:', errors);
        if (!isValid) return toast({
            title: t('prompt'),
            variant: 'error',
            description: Object.keys(errors).map(key => errors[key]),
        })

        onSave(formData)
        !online && appConfig.securityCommitment && setCommitmentApi(id, commitmentId)
    };

    const uploadAvator = (file) => {
        uploadFileWithProgress(file, (progress) => { }, 'icon').then(res => {
            setFormData(prev => ({ ...prev, logo: res.file_path }));
        })
    }

    return <DialogContent className="sm:max-w-[625px] bg-background-login">
        <DialogHeader>
            <DialogTitle>{t('build.editAssistant')}</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-8 py-6">
            <div className="">
                <label htmlFor="name" className="bisheng-label">{t('build.assistantAvatar')}<span className="bisheng-tip">*</span></label>
                <Avator
                    value={formData.logo}
                    className="mt-2"
                    onChange={uploadAvator}
                ><AssistantIcon className="bg-primary w-9 h-9 rounded-sm" /></Avator>
                {errors.name && <p className="bisheng-tip mt-1">{errors.name}</p>}
            </div>
            <div className="">
                <label htmlFor="name" className="bisheng-label">{t('build.assistantName')}<span className="bisheng-tip">*</span></label>
                <Input
                    id="name"
                    name="name"
                    placeholder={t('build.enterName')}
                    maxLength={50}
                    showCount
                    className="mt-2"
                    value={formData.name}
                    onChange={handleChange}
                />
                {errors.name && <p className="bisheng-tip mt-1">{errors.name}</p>}
            </div>
            <div className="">
                <label htmlFor="desc" className="bisheng-label">{t('build.assistantDesc')}</label>
                <Textarea
                    id="desc"
                    name="desc"
                    placeholder={t('build.enterDesc')}
                    maxLength={1000}
                    className="mt-2"
                    value={formData.desc}
                    onChange={handleChange}
                />
                {errors.desc && <p className="bisheng-tip mt-1">{errors.desc}</p>}
            </div>
            {appConfig.securityCommitment && <div className="mb-6">
                <label className="bisheng-label">承诺书:</label>
                <SelectCommitment value={commitmentId} onChange={setCommitmentId} />
            </div>}
        </div>
        <DialogFooter>
            <DialogClose>
                <Button variant="outline" className="px-11" type="button">{t('build.cancel')}</Button>
            </DialogClose>
            <Button type="submit" className="px-11" onClick={handleSubmit}>{t('build.confirm')}</Button>
        </DialogFooter>
    </DialogContent>
};

