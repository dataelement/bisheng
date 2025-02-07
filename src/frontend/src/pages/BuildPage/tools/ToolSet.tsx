import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { updateAssistantToolApi } from "@/controllers/API/assistant";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { forwardRef, useImperativeHandle, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import BingToolForm from "./builtInTool/BingSearch";
import JinaApiKeyForm from "./builtInTool/JinaConfig";
import TianyanchaToolForm from "./builtInTool/Tianyancha";
import Dalle3ToolForm from "./builtInTool/Dalle3";
import FeishuConfigForm from "./builtInTool/FeishuConfig";
import SiliconFlowApiKeyForm from "./builtInTool/SiliconFlowApiKey";
import EmailConfigForm from "./builtInTool/EmailConfig";
import CrawlerConfigForm from "./builtInTool/CrawlerConfig";

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

    useImperativeHandle(ref, () => ({
        edit: (item) => {
            setName(item.name);
            idRef.current = item.id;
            const configStr = item.children[0]?.extra;
            if (configStr) {
                const config = JSON.parse(configStr);
                // config.provider = config.azure_deployment ? 'azure' : 'openai';
                // const apiKey = config.openai_api_key;
                // if (config.provider === 'openai') {
                //     config.openai_api_key = apiKey;
                //     config.azure_api_key = '';
                // } else {
                //     config.openai_api_key = '';
                //     config.azure_api_key = apiKey;
                // }
                setFormData(config);
            } else {
                // resetFormData();
            }
            setOpen(true);
        }
    }));



    const handleSubmit = async (formdata) => {
        await captureAndAlertRequestErrorHoc(updateAssistantToolApi(idRef.current, formdata));
        setOpen(false);
        message({ variant: 'success', description: t('build.saveSuccess') });
        onChange();
    };

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
            case '飞书发送消息':
                return <FeishuConfigForm formData={formData} onSubmit={handleSubmit} />;
            case 'Bing web搜索':
                return <BingToolForm formData={formData} onSubmit={handleSubmit} />;
            case '天眼查':
                return <TianyanchaToolForm formData={formData} onSubmit={handleSubmit} />;
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
