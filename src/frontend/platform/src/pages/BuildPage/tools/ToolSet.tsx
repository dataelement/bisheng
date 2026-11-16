// @ts-strict-ignore
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";

import { updateToolApi } from "@/controllers/API/tools";
import { forwardRef, useImperativeHandle, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import BingToolForm from "./builtInTool/BingSearch";
import CodeExecutor from "./builtInTool/CodeExecutor";
import CrawlerConfigForm from "./builtInTool/CrawlerConfig";
import ImageGeneration from "./builtInTool/ImageGeneration";
import EmailConfigForm from "./builtInTool/EmailConfig";
import FeishuConfigForm from "./builtInTool/FeishuConfig";
import JinaApiKeyForm from "./builtInTool/JinaConfig";
import SiliconFlowApiKeyForm from "./builtInTool/SiliconFlowApiKey";
import TianyanchaToolForm from "./builtInTool/Tianyancha";
import WebSearchForm from "./builtInTool/WebSearchFrom";
import { useWebSearchStore } from './webSearchStore';
import FinancialDataToolForm from "./builtInTool/FinancialData";
import { WebFetchForm } from "./builtInTool/WebFetchForm";
const ToolSet = forwardRef(function ToolSet({ onChange }, ref) {
    const [open, setOpen] = useState(false);
    const { t } = useTranslation();
    const [formData, setFormData] = useState(null)

    // {
    //     provider: 'openai',
    //     openai_api_key: '',
    //     azure_api_key: '',
    //     openai_api_base: 'https://api.openai.com/v1',
    //     openai_proxy: '',
    //     bing_subscription_key: '',
    //     bing_search_url: 'https://api.bing.microsoft.com/v7.0/search',
    //     azure_deployment: '',
    //     azure_endpoint: '',
    //     openai_api_version: ''
    // });
    const idRef = useRef('');
    const [name, setName] = useState('');
    const [toolKeys, setToolKeys] = useState<string[]>([]);
    const { setConfig } = useWebSearchStore()

    useImperativeHandle(ref, () => ({

        edit: (item) => {

            setName(item.name);
            setToolKeys((item.children || []).map((child) => child.tool_key));
            idRef.current = item.id;
            let config = {};
            try {
                if (item.extra) {
                    config = JSON.parse(item.extra);
                }
            } catch (e) {
                console.error('api error');
            }
            setFormData(config);
            setOpen(true);
        }
    }));



    const handleSubmit = async (formdata) => {
        await updateToolApi(idRef.current, formdata)
        if (!toolKeys.some(key => ['image_generation', 'dalle_image_generator'].includes(key))) setConfig(formdata)
        setOpen(false)
        onChange()
    }

    const handleCancel = () => {
        setOpen(false);
    };

    const renderFormContent = () => {
        if (toolKeys.includes('web_fetch')) {
            return <WebFetchForm formData={formData} onSubmit={handleSubmit} />;
        }
        if (toolKeys.some(key => ['image_generation', 'dalle_image_generator'].includes(key))) {
            return <ImageGeneration formData={formData} onSubmit={handleSubmit} />;
        }
        switch (name) {
            case 'Firecrawl':
                return <CrawlerConfigForm formData={formData} onSubmit={handleSubmit} />;
            case 'Jina AI':
                return <JinaApiKeyForm formData={formData} onSubmit={handleSubmit} />;
            case 'SiliconFlow':
                return <SiliconFlowApiKeyForm formData={formData} onSubmit={handleSubmit} />;
            case '发送邮件':
                return <EmailConfigForm formData={formData} onSubmit={handleSubmit} />;
            case '飞书消息':
                return <FeishuConfigForm formData={formData} onSubmit={handleSubmit} />;
            case 'Bing web搜索':
                return <BingToolForm formData={formData} onSubmit={handleSubmit} />;
            case '天眼查':
                return <TianyanchaToolForm formData={formData} onSubmit={handleSubmit} />;
            case '联网搜索':
                return <WebSearchForm toolId={idRef.current} onSaved={() => { setOpen(false); onChange(); }} />;
            case '代码执行器':
                return <CodeExecutor formData={formData} onSubmit={handleSubmit} />;
            case '经济金融数据':
                return <FinancialDataToolForm formData={formData} onSubmit={handleSubmit} />;
            default:
                return null;
        }
    };

    return (
        <Dialog open={open} onOpenChange={setOpen}>
            <DialogContent className="sm:max-w-[625px] bg-background-login">
                <DialogHeader>
                    <DialogTitle>{t('build.editTool')}</DialogTitle>
                </DialogHeader>
                {renderFormContent()}
            </DialogContent>
        </Dialog>
    );
});

export default ToolSet;
