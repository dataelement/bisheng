// F035: 应用 tab — app-center welcome message and description, moved out of
// the home tab. Both fields still persist into the daily workstation config:
// the full config is loaded on mount and round-tripped on save with only
// these two fields replaced (tab content remounts on switch, so the loaded
// snapshot stays fresh).
import { Button } from "@/components/bs-ui/button";
import { CardContent } from "@/components/bs-ui/card";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { locationContext } from "@/contexts/locationContext";
import { getDailyConfigApi, setDailyConfigApi } from "@/controllers/API";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { useContext, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import ConfigInheritanceBanner, { resolveConfigEnvelope } from "./ConfigInheritanceBanner";
import { FormInput } from "./FormInput";

const MAX_LEN = 1000;

export function AppCenter({ scopeVersion = 0 }: { scopeVersion?: number }) {
    const { t } = useTranslation();
    const { toast } = useToast();
    const { reloadConfig } = useContext(locationContext);
    const [welcome, setWelcome] = useState('');
    const [description, setDescription] = useState('');
    const [errors, setErrors] = useState({ welcome: '', description: '' });
    const [configMeta, setConfigMeta] = useState<any>(null);
    // Full loaded config — round-tripped on save so home-tab fields survive.
    const loadedCfgRef = useRef<any>(null);

    useEffect(() => {
        setConfigMeta(null);
        getDailyConfigApi().then((res) => {
            const { data: cfg, meta } = resolveConfigEnvelope<any>(res);
            setConfigMeta(meta);
            loadedCfgRef.current = cfg || {};
            setWelcome(cfg?.applicationCenterWelcomeMessage ?? '');
            setDescription(cfg?.applicationCenterDescription ?? '');
        });
    }, [scopeVersion]);

    const handleChange = (field: 'welcome' | 'description', value: string) => {
        (field === 'welcome' ? setWelcome : setDescription)(value);
        setErrors(prev => ({
            ...prev,
            [field]: value.length >= MAX_LEN ? t('chatConfig.errors.maxCharacters', { count: MAX_LEN }) : '',
        }));
    };

    const handleSave = () => {
        const dataToSave = {
            ...(loadedCfgRef.current || {}),
            applicationCenterWelcomeMessage: welcome.trim() || t('chatConfig.appCenterWelcomePlaceholder'),
            applicationCenterDescription: description.trim() || t('chatConfig.appCenterDescriptionPlaceholder'),
        };
        captureAndAlertRequestErrorHoc(setDailyConfigApi(dataToSave)).then((res) => {
            if (res) {
                setConfigMeta({ inherited_from_root: false, has_override: true });
                toast({ variant: 'success', description: t('chatConfig.saveSuccess') });
                reloadConfig();
            }
        });
    };

    return (
        <div className="h-full overflow-y-scroll scrollbar-hide relative border-t">
            <div className="pt-4 relative">
                <CardContent className="pt-4 relative">
                    <div className="w-full max-h-[calc(100vh-180px)] overflow-y-scroll scrollbar-hide pb-10">
                        <ConfigInheritanceBanner meta={configMeta} />
                        <FormInput
                            label={t('chatConfig.appCenterWelcome')}
                            value={welcome}
                            error={errors.welcome}
                            placeholder={t('chatConfig.appCenterWelcomePlaceholder')}
                            maxLength={MAX_LEN}
                            onChange={(v) => handleChange('welcome', v)}
                        />
                        <FormInput
                            label={t('chatConfig.appCenterDescription')}
                            value={description}
                            error={errors.description}
                            placeholder={t('chatConfig.appCenterDescriptionPlaceholder')}
                            maxLength={MAX_LEN}
                            onChange={(v) => handleChange('description', v)}
                        />
                    </div>
                    <div className="flex justify-end gap-4 absolute bottom-1 right-4">
                        <Button onClick={handleSave}>{t('save')}</Button>
                    </div>
                </CardContent>
            </div>
        </div>
    );
}
