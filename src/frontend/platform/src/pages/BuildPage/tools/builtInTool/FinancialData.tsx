import { Button } from "@/components/bs-ui/button";
import { DialogClose, DialogFooter } from "@/components/bs-ui/dialog";
import { useEffect, useState } from 'react';
import { useTranslation } from "react-i18next";
import { HelpCircle } from "lucide-react";
import { InputField } from "./InputField";

/**
 * Component for editing economic and financial data tool settings.
 * Focuses specifically on network configurations like proxy settings.
 */
const FinancialDataToolForm = ({ formData, onSubmit }) => {
    const { t } = useTranslation();
    const [localFormData, setLocalFormData] = useState(() => ({ proxy: '', ...formData }));

    useEffect(() => {
        setLocalFormData((prev) => ({ ...prev, ...formData }));
    }, [formData]);

    const handleChange = (e) => {
        const { name, value } = e.target;
        setLocalFormData((prev) => ({ ...prev, [name]: value }));
    };

    const handleSubmit = (e) => {
        e.preventDefault();
        // Proxy is optional, so no heavy validation needed
        onSubmit(localFormData);
    };

    return (
        <form onSubmit={handleSubmit} className="flex flex-col gap-4" autoComplete="off">
            <div className="space-y-2">
                <InputField
                    id="proxy"
                    name="proxy"
                    label="proxy"
                    tooltip={t('build.proxyDescription')}
                    placeholder={t('build.enterProxy')}
                    value={localFormData.proxy}
                    onChange={handleChange}
                />
            </div>

            <DialogFooter>
                <DialogClose asChild>
                    <Button variant="outline" className="px-11" type="button">
                        {t('build.cancel')}
                    </Button>
                </DialogClose>
                <Button className="px-11" type="submit">
                    {t('build.confirm')}
                </Button>
            </DialogFooter>
        </form>
    );
};

export default FinancialDataToolForm;