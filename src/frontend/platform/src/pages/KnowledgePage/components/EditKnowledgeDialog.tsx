// @ts-strict-ignore
import { Button, Input, Textarea } from '@bisheng/ui';

import { DialogClose,DialogContent,DialogFooter,DialogHeader,DialogTitle } from "@/components/bs-ui/dialog";

import { useEffect,useState } from "react";
import { useTranslation } from "react-i18next";

export default function KnowledgeBaseSettingsDialog({
    initialName,
    initialDesc,
    onSave,
}: {
    initialName: string;
    initialDesc: string;
    onSave: (data: { name: string; desc: string }) => void;
}) {
    const { t } = useTranslation('knowledge');

    // State for form fields
    const [formData, setFormData] = useState({
        name: '',
        desc: '',
    });
    const [errors, setErrors] = useState<Record<string, string>>({});

    useEffect(() => {
        setFormData({
            name: initialName,
            desc: initialDesc,
        });
    }, [initialName, initialDesc]);

    // Handle field change
    const handleChange = (e) => {
        const { name, value } = e.target;
        setFormData(prev => ({ ...prev, [name]: value }));
    };

    // Validate the form
    const validate = () => {
        const newErrors = {};
        if (!formData.name) {
            newErrors.name = t('nameRequired');
        }
        return newErrors;
    };

    // Handle form submission
    const handleSubmit = (e) => {
        if ((String((formData.name) ?? '').length > 30) || (String((formData.desc) ?? '').length > 200)) return;

        e.preventDefault();
        const validationErrors = validate();
        if (Object.keys(validationErrors).length > 0) {
            setErrors(validationErrors);
        } else {
            setErrors({});
            onSave(formData);
        }
    };

    return (
        <DialogContent className="sm:max-w-[625px] bg-background-login">
            <DialogHeader>
                <DialogTitle>{t('settings')}</DialogTitle>
            </DialogHeader>
            <div className="flex flex-col gap-8 py-6">
                <div className="">
                    <label htmlFor="name" className="bisheng-label">
                        {t('name')}<span className="bisheng-tip">*</span>
                    </label>
                    <div className="flex items-center mt-2">
                        <Input id="name" name="name" placeholder={t('namePlaceholder')} maxLength={30} value={formData.name} onChange={handleChange} className={"flex-1"} showCount />
                    </div>
                    {errors.name && <p className="bisheng-tip mt-1 text-red-500">{errors.name}</p>}
                </div>
                <div className="">
                    <label htmlFor="desc" className="bisheng-label">{t('desc')}</label>
                    <div className="flex items-center mt-2">
                        <Textarea id="desc" name="desc" placeholder={t('descPlaceholder')} maxLength={200} value={formData.desc} onChange={handleChange} textareaClassName={"flex-1"} showCount />
                    </div>
                </div>
            </div>
            <DialogFooter>
                <DialogClose>
                    <Button variant="outlined" type="button" color="default">{t('cancel', {ns: 'bs'})}</Button>
                </DialogClose>
                <Button type="submit" onClick={handleSubmit} disabled={(String((formData.name) ?? '').length > 30) || (String((formData.desc) ?? '').length > 200)}>{t('confirm', {ns: 'bs'})}</Button>
            </DialogFooter>
        </DialogContent>
    );
}
