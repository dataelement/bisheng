import i18next from "i18next"
import { useEffect, useContext } from "react"
import { locationContext } from "../../../contexts/locationContext"
import { useToast } from "@/components/bs-ui/toast/use-toast"
import { useTranslation } from "react-i18next"
import { getOfficeTokenApi } from "@/controllers/API/flow"

export default function Word({ data, workflow }) {
    const { appConfig } = useContext(locationContext)
    const { t } = useTranslation('flow')

    const wordUrl = appConfig.officeUrl
    // Local debug
    // const host = 'http://192.168.106.120:3002'
    const host = `${location.origin}${__APP_ENV__.BASE_URL}`
    const backUrl = workflow ? `${host}/api/v1/workflow/report/callback`
        : `${host}/api/v1/report/callback` // Backend callback URL

    const editorConfig = {
        // Editor width
        width: '100%',
        // Editor height
        height: '100%',
        // Editor type: word (document), cell (spreadsheet), slide (PPT)
        documentType: 'word',
        // Document config
        document: {
            // File type  
            fileType: 'docx',
            // Document identifier
            key: data.key,
            // Document URL, absolute path
            url: data.path,
            // Document title
            title: 'bisheng.docx',
            permissions: {
                changeHistory: true,
                comment: true,
                copy: true,
                download: true,
                edit: true,
                print: true,
                reader: true,
                rename: false,
                review: true
            }
        },
        editorConfig: {
            callbackUrl: backUrl,
            lang: i18next.language === 'zh-Hans' ? "zh-CN" : 'en',
            mode: "edit",
            customization: {
                anonymous: { request: false, label: "" },
                comments: false,
                customer: false,
                help: false,
                chat: false,
                about: false,
                features: { spellcheck: false },
                forcesave: true,
                hideRightMenu: true,
                rightMenu: true,
                unit: "cm",
                uiTheme: "theme-dark",
                logo: {
                    "image": location.origin + __APP_ENV__.BASE_URL + "/assets/bisheng/logo.jpeg",
                    "imageDark": location.origin + __APP_ENV__.BASE_URL + "/assets/bisheng/logo.jpeg",
                    "url": "https://example.com"
                }
            },
            plugins: {
                autostart: ['asc.{D2A0F3BE-CC8D-4956-BCD9-6CBEA6E8960E}']
                // pluginsData: ['ommon-plugins/config.json']
            },
            user: {
                group: "Group1",
                id: "001",
                name: ""
            }
        }
    }


    const createEditor = (config) => {
        window.editor = new window.DocsAPI.DocEditor('bsoffice', config)
    }

    // Sign editorConfig with JWT and then create editor
    const initEditor = async () => {
        let finalConfig = { ...editorConfig }
        try {
            const res = await getOfficeTokenApi(editorConfig)
            if (res.token) {
                finalConfig.token = res.token
            }
        } catch (e) {
            // If token request fails, proceed without token (for non-JWT setups)
            console.warn('Failed to get OnlyOffice JWT token, proceeding without it:', e)
        }
        createEditor(finalConfig)
    }

    const { toast } = useToast()
    useEffect(() => {
        if (window.DocsAPI) {
            initEditor()
        } else {
            if (!wordUrl) {
                toast({
                    variant: 'error',
                    title: t('wordEditorLoadFailed'), // 'word编辑器加载失败',
                    description: t('checkOfficeServiceConfig') // '请检查Office服务地址配置是否正确并正常启动.'
                })
            }
            const script = document.createElement('script')
            script.src = wordUrl + '/web-apps/apps/api/documents/api.js' // OnlyOffice editor service
            script.onload = initEditor
            document.head.appendChild(script)
            script.onerror = () => {
                toast({
                    variant: 'error',
                    title: t('wordEditorLoadFailed'), // 'word编辑器加载失败',
                    description: t('checkOfficeServiceConfig') // '请检查Office服务地址配置是否正确并正常启动.'
                })
            }
        }

        return () => {
            console.log('destroyEditor :>> ');
            window.editor?.destroyEditor();
        }
    }, [])

    return <div className="relative w-full h-full">
        <div className="absolute bg-[#252525] left-0 top-0 h-[26px] leading-[26px] w-full text-gray-400 text-center text-xs">ctrl+s to save</div>
        <div id="bsoffice"></div>
    </div>
};
