import { useState, useEffect } from 'react';

interface ProviderInfo {
    apiKeyUrl: string;
    modelUrl: string;
}

// API数据映射
const modelProviderInfo: Record<string, ProviderInfo> = {
    tencent: {
        apiKeyUrl: 'https://console.cloud.tencent.com/hunyuan/settings',
        modelUrl: 'https://console.cloud.tencent.com/hunyuan/start',
    },
    qwen: {
        apiKeyUrl: 'https://bailian.console.aliyun.com/?tab=model#/api-key',
        modelUrl: 'https://bailian.console.aliyun.com/?tab=model#/model-market',
    },
    volcengine: {
        apiKeyUrl: 'https://console.volcengine.com/las/region:las+cn-beijing/next/api_key_management/list?current=1&pageSize=10',
        modelUrl: 'https://console.volcengine.com/ark/region:ark+cn-beijing/model',
    },
    qianfan: {
        apiKeyUrl: 'https://console.bce.baidu.com/iam/#/iam/apikey/list',
        modelUrl: 'https://console.bce.baidu.com/qianfan/modelcenter/model/buildIn/list',
    },
    spark: {
        apiKeyUrl: 'https://console.xfyun.cn/app/myapp',
        modelUrl: 'https://www.xfyun.cn/doc/spark/Web.html#_1-%E6%8E%A5%E5%8F%A3%E8%AF%B4%E6%98%8E',
    },
    minimax: {
        apiKeyUrl: 'https://platform.minimaxi.com/user-center/basic-information/interface-key',
        modelUrl: 'https://platform.minimaxi.com/docs/guides/models-intro',
    },
    moonshot: {
        apiKeyUrl: 'https://platform.moonshot.cn/console/api-keys',
        modelUrl: 'https://platform.moonshot.cn/docs/api/chat#%E5%AD%97%E6%AE%B5%E8%AF%B4%E6%98%8E',
    },
    zhipu: {
        apiKeyUrl: 'https://bigmodel.cn/usercenter/proj-mgmt/apikeys',
        modelUrl: 'https://docs.bigmodel.cn/cn/guide/start/model-overview',
    },
    silicon: {
        apiKeyUrl: 'https://cloud.siliconflow.cn/me/account/ak',
        modelUrl: 'https://cloud.siliconflow.cn/me/models',
    },
    deepseek: {
        apiKeyUrl: 'https://platform.deepseek.com/api_keys',
        modelUrl: 'https://platform.deepseek.com/docs',
    },
};

// 获取API信息
export function useModelProviderInfo(providerValue: string): ProviderInfo | null {
    const [providerInfo, setProviderInfo] = useState<ProviderInfo | null>(null);

    useEffect(() => {
        if (modelProviderInfo[providerValue]) {
            setProviderInfo(modelProviderInfo[providerValue]);
        } else {
            setProviderInfo(null);
        }
    }, [providerValue]);

    return providerInfo;
}