// @ts-strict-ignore
import { Button, notification, toast } from '@bisheng/ui';
import { useContext, useEffect, useRef, useState } from "react";
import AceEditor from "react-ace";
import { useTranslation } from "react-i18next";

import { getSysConfigApi, setSysConfigApi } from "../../../controllers/API/user";
import { showApiError } from "../../../controllers/request";
import { locationContext } from "@/contexts/locationContext";
import { KunlianAutoOnboardingCard } from "./KunlianAutoOnboardingCard";
import {
    KunlianAutoOnboardingSetting,
    parseKunlianAutoOnboardingYaml,
    updateKunlianAutoOnboardingYaml,
} from "./kunlianConfigYaml";


export default function Config() {

    const { appConfig, reloadConfig } = useContext(locationContext)

    const [config, setConfig] = useState('')
    const [loaded, setLoaded] = useState(false)
    const [yamlOverride, setYamlOverride] = useState<KunlianAutoOnboardingSetting>('inherit')
    const [savingKunlian, setSavingKunlian] = useState(false)

    const { t } = useTranslation()

    useEffect(() => {
        getSysConfigApi().then(jsonstr => {
            setConfig(jsonstr)
            codeRef.current = jsonstr
            setYamlOverride(parseKunlianAutoOnboardingYaml(jsonstr))
            setLoaded(true)
        }).catch(showApiError)
    }, [])

    const handleSave = () => {
        if (!loaded) return
        if (validataRef.current.length) {
            return notification.open({ type: 'error', title: String(`yaml${t('formatError')}`), description: (validataRef.current.map(el => el.text)).filter(Boolean).join('\n') })
        }

        setSysConfigApi({ data: codeRef.current }).then(res => {
            toast.show({ type: 'success', message: [String(t('prompt') ?? ''), String(t('saved') ?? '')].filter(Boolean).join('\n') })
            setConfig(codeRef.current)
            setYamlOverride(parseKunlianAutoOnboardingYaml(codeRef.current))

            // 更新配置信息
            reloadConfig()
        }).catch(showApiError)
    }

    const persistKunlianAutoOnboarding = (nextSetting: KunlianAutoOnboardingSetting) => {
        if (!loaded || savingKunlian) return
        if (validataRef.current.length) {
            return notification.open({ type: 'error', title: String(`yaml${t('formatError')}`), description: (validataRef.current.map(el => el.text)).filter(Boolean).join('\n') })
        }

        const prevYaml = codeRef.current || config
        const prevOverride = yamlOverride
        const nextYaml = updateKunlianAutoOnboardingYaml(prevYaml, nextSetting)

        codeRef.current = nextYaml
        setConfig(nextYaml)
        setYamlOverride(nextSetting)
        setSavingKunlian(true)

        setSysConfigApi({ data: nextYaml })
            .then(() => {
                toast.show({ type: 'success', message: [String(t('prompt') ?? ''), String(t('saved') ?? '')].filter(Boolean).join('\n') })
                reloadConfig()
            })
            .catch((error) => {
                // Roll back optimistic state on save failure so Switch matches persisted YAML.
                codeRef.current = prevYaml
                setConfig(prevYaml)
                setYamlOverride(prevOverride)
                showApiError(error)
            })
            .finally(() => {
                setSavingKunlian(false)
            })
    }

    const codeRef = useRef('')
    const validataRef = useRef([])
    return <div className="flex h-full max-w-[80%] mx-auto flex-col pt-6 pb-4">
        <p className="font-bold mb-2 shrink-0">{t('system.parameterConfig')}</p>
        {appConfig?.kunlianSsoConfigured && (
            <KunlianAutoOnboardingCard
                yamlOverride={yamlOverride}
                deploymentDefault={Boolean(appConfig?.kunlianAutoOnboardingDefault)}
                loaded={loaded}
                saving={savingKunlian}
                onToggle={(nextEnabled) => persistKunlianAutoOnboarding(nextEnabled)}
                onResetInherit={() => persistKunlianAutoOnboarding('inherit')}
            />
        )}
        <AceEditor
            width="100%"
            value={config || ''}
            mode="yaml"
            theme={"twilight"}
            highlightActiveLine={true}
            showPrintMargin={false}
            fontSize={14}
            showGutter
            enableLiveAutocompletion
            name="CodeEditor"
            onChange={(value) => {
                codeRef.current = value
                setYamlOverride(parseKunlianAutoOnboardingYaml(value))
            }}
            onValidate={(e) => validataRef.current = e}
            className="min-h-0 w-full flex-1 rounded-lg border-[1px] border-border custom-scroll"
        />
        <div className="flex justify-center mt-4 shrink-0">
            <Button disabled={!loaded} onClick={handleSave}>{t('save')}</Button>
        </div>
    </div>
};
