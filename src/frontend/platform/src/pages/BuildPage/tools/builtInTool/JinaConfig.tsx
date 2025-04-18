import { Button } from '@/components/bs-ui/button';
import { DialogClose, DialogFooter } from "@/components/bs-ui/dialog";
import { useState } from 'react';
import { useTranslation } from "react-i18next";
import { InputField } from "./InputField";

const defaultValues = {
    jina_api_key: '',
};

const JinaApiKeyForm = ({ formData = {}, onSubmit }) => {
    const { t } = useTranslation();
    const [localFormData, setLocalFormData] = useState(() => ({ ...defaultValues, ...formData }));

    const handleChange = (e) => {
        const { name, value } = e.target;
        setLocalFormData((prev) => ({ ...prev, [name]: value }));
    };

    const handleSubmit = (e) => {
        e.preventDefault();
        onSubmit(localFormData);
    };

    return (
        <form onSubmit={handleSubmit} className="flex flex-col gap-6">
            {/* Jina API Key Input */}
            <InputField
                label="Jina API 密钥"
                type="password"
                id="jina_api_key"
                name="jina_api_key"
                placeholder={''}
                value={localFormData.jina_api_key}
                onChange={handleChange}
            />

            {/* Dialog Footer */}
            <DialogFooter>
                <DialogClose>
                    <Button variant="outline" className="px-11" type="button">
                        {t('cancel')}
                    </Button>
                </DialogClose>
                <Button className="px-11" type="submit">
                    {t('save')}
                </Button>
            </DialogFooter>
        </form>
    );
};

export default JinaApiKeyForm;
