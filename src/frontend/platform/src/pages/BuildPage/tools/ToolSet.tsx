import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { updateToolApi } from "@/controllers/API/tools";
import { forwardRef, useImperativeHandle, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import BingToolForm from "./builtInTool/BingSearch";
import CodeExecutor from "./builtInTool/CodeExecutor";
import CrawlerConfigForm from "./builtInTool/CrawlerConfig";
import Dalle3ToolForm from "./builtInTool/Dalle3";
import EmailConfigForm from "./builtInTool/EmailConfig";
import FeishuConfigForm from "./builtInTool/FeishuConfig";
import JinaApiKeyForm from "./builtInTool/JinaConfig";
import SiliconFlowApiKeyForm from "./builtInTool/SiliconFlowApiKey";
import TianyanchaToolForm from "./builtInTool/Tianyancha";
import WebSearchForm from "./builtInTool/WebSearchFrom";
import { useWebSearchStore } from './webSearchStore';
import FinancialDataToolForm from "./builtInTool/FinancialData";
const ToolSet = forwardRef(function ToolSet({ onChange }, ref) {
    const [open, setOpen] = useState(false);
    const { t } = useTranslation();
    const [formData, setFormData] = useState(null)
    const { message } = useToast();
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
    const { setConfig } = useWebSearchStore()

    useImperativeHandle(ref, () => ({

        edit: (item) => {

            setName(item.name);
            idRef.current = item.id;
            let config = {};
            try {
                if (item.extra) {
                    config = JSON.parse(item.extra);
                    console.log('Parsed extra config:', config);
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
        setConfig(formdata)
        setOpen(false)
        onChange()
    }

    // const getFieldsToSubmit = () => {
    //     const fields = {};
    //     if (name === 'Dalle3绘画') {
    //         if (formData.provider === 'openai') {
    //             fields.openai_api_key = formData.openai_api_key;
    //             fields.openai_api_base = formData.openai_api_base;
    //             fields.openai_proxy = formData.openai_proxy;
    //         } else {
    //             fields.openai_api_key = formData.azure_api_key;
    //             fields.azure_deployment = formData.azure_deployment;
    //             fields.azure_endpoint = formData.azure_endpoint;
    //             fields.openai_api_version = formData.openai_api_version;
    //             fields.openai_api_type = 'azure';
    //         }
    //     } else if (name === 'Bing web搜索') {
    //         fields.bing_subscription_key = formData.bing_subscription_key;
    //         fields.bing_search_url = formData.bing_search_url;
    //     } else if (name === '天眼查') {
    //         fields.api_key = formData.api_key;
    //     }
    //     return fields;
    // };

    const handleCancel = () => {
        setOpen(false);
    };

    const renderFormContent = () => {
        switch (name) {
            case 'Dalle3绘画':
                return <Dalle3ToolForm formData={formData} onSubmit={handleSubmit} />;
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
                return <WebSearchForm formData={formData} onSubmit={handleSubmit} />;
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
