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
import { clampMenuName } from "./menuDisplayName";

const MAX_LEN = 1000;

export function AppCenter({ scopeVersion = 0 }: { scopeVersion?: number }) {
    const { t } = useTranslation();
    const { toast } = useToast();
    const { reloadConfig } = useContext(locationContext);
    const [welcome, setWelcome] = useState('');
    const [description, setDescription] = useState('');
    // Sidebar entry name for the app-center module — required, defaults to the tab name.
    const [menuDisplayName, setMenuDisplayName] = useState(() => t('bench.appCenter'));
    const [errors, setErrors] = useState({ welcome: '', description: '', menuDisplayName: '' });
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
            // 空字符串同样视为「未配置」，回落到默认菜单名
            const savedMenuName = (cfg?.appCenterMenuDisplayName ?? '').trim();
            setMenuDisplayName(savedMenuName || t('bench.appCenter'));
        });
    }, [scopeVersion, t]);

    const handleChange = (field: 'welcome' | 'description', value: string) => {
        (field === 'welcome' ? setWelcome : setDescription)(value);
        setErrors(prev => ({
            ...prev,
            [field]: value.length >= MAX_LEN ? t('chatConfig.errors.maxCharacters', { count: MAX_LEN }) : '',
        }));
    };

    const handleSave = () => {
        // 菜单显示名称必填（长度在输入时已截断）
        if (!menuDisplayName.trim()) {
            setErrors(prev => ({ ...prev, menuDisplayName: t('chatConfig.errors.required') }));
            return;
        }
        const dataToSave = {
            ...(loadedCfgRef.current || {}),
            appCenterMenuDisplayName: menuDisplayName.trim(),
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
                <CardContent className="pt-4 pb-0 relative">
                    <div className="w-full max-h-[calc(var(--bs-vh,100vh)-180px-var(--license-banner-h,0px))] overflow-y-scroll scrollbar-hide pb-10">
                        <ConfigInheritanceBanner meta={configMeta} />
                        <FormInput
                            label={t('chatConfig.menuDisplayName')}
                            value={menuDisplayName}
                            error={errors.menuDisplayName}
                            placeholder={t('bench.appCenter')}
                            onChange={(v) => {
                                setMenuDisplayName(clampMenuName(v));
                                setErrors(prev => ({ ...prev, menuDisplayName: '' }));
                            }}
                        />
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
