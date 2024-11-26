import i18next from "i18next"
import { useEffect, useContext } from "react"
import { locationContext } from "../../../contexts/locationContext"

export default function Word({ data, workflow }) {
    const { appConfig } = useContext(locationContext)

    const wordUrl = appConfig.officeUrl
    const backUrl = workflow ? `${location.origin}${__APP_ENV__.BASE_URL}/api/v1/workflow/report/callback`
    : `${location.origin}${__APP_ENV__.BASE_URL}/api/v1/report/callback` // 后端服务地址

    const editorConfig = {
        // 编辑器宽度
        width: '100%',
        // 编辑器高度
        height: '100%',
        // 编辑器类型，支持 word（文档）、cell（表格）、slide（PPT）
        documentType: 'word',
        // 文档配置
        document: {
            // 文件类型  
            fileType: 'docx',
            // 文档标识符
            key: data.key,
            // 文档地址，绝对路径
            url: data.path,
            // 文档标题
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
            lang: i18next.language === 'zh' ? "zh-CN" : 'en',
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
                    "image": location.origin + __APP_ENV__.BASE_URL + "/logo.jpeg",
                    "imageDark": location.origin + __APP_ENV__.BASE_URL + "/logo.jpeg",
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


    const createEditor = () => {
        window.editor = new window.DocsAPI.DocEditor('bsoffice', editorConfig)
    }

    useEffect(() => {
        if (window.DocsAPI) {
            createEditor()
        } else {
            const script = document.createElement('script')
            script.src = wordUrl + '/web-apps/apps/api/documents/api.js' // 在线编辑服务
            script.onload = createEditor
            document.head.appendChild(script)
        }

        return () => {
            console.log('destroyEditor :>> ');
            window.editor.destroyEditor();
        }
    }, [])

    return <div className="relative w-full h-full">
        <div className="absolute bg-[#252525] left-0 top-0 h-[26px] leading-[26px] w-full text-gray-400 text-center text-xs">ctrl+s to save</div>
        <div id="bsoffice"></div>
    </div>
};

