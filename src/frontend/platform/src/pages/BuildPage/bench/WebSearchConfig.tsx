import { Input, Textarea } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select";
import { useEffect, useState } from "react";

export const WebSearchConfig = ({
    config,
    onChange,
    errors = {}
}: {
    config: {
        tool: string;
        params: {
            api_key?: string;
            base_url?: string;
            engine?: string;
        };
        prompt: string;
    };
    onChange: (field: string, value: any) => void;
    errors?: Record<string, any>;
}) => {
    // Store parameters for all tools separately
    const [toolsParams, setToolsParams] = useState<Record<string, any>>({
        bing: { api_key: '', base_url: '' },
        bocha: { api_key: '' },
        jina: { api_key: '' },
        serp: { api_key: '', engine: '' },
        tavily: { api_key: '' }
    });

    // Initialize toolsParams with existing config
    useEffect(() => {
        if (config.tool && config.params) {
            setToolsParams(prev => ({
                ...prev,
                [config.tool]: { ...prev[config.tool], ...config.params }
            }));
        }
    }, [config]);

    // Handle parameter changes for the current tool
    const handleParamChange = (field: string, value: string) => {
        const updatedParams = {
            ...toolsParams,
            [config.tool]: {
                ...toolsParams[config.tool],
                [field]: value
            }
        };

        setToolsParams(updatedParams);

        // Update the config.params with current tool's parameters
        onChange('params', updatedParams[config.tool]);
    };

    // Handle tool change
    const handleToolChange = (val: string) => {
        // First update the tool
        onChange('tool', val);

        // Then update params with the new tool's saved parameters
        onChange('params', toolsParams[val]);
    };

    // Render parameters based on current tool
    const renderParams = () => {
        const currentParams = toolsParams[config.tool] || {};

        switch (config.tool) {
            case 'bing':
                return (
                    <>
                        <Label className="bisheng-label text-sky-900 mt-4 block">Bing Subscription Key <span className="text-red-500">*</span></Label>
                        <div className="mt-3">
                            <Input
                                type="password"
                                value={currentParams.api_key || ''}
                                onChange={(e) => handleParamChange('api_key', e.target.value)}
                            />
                            {errors.params?.api_key && <span className="text-red-500 text-sm">Bing Subscription Key {errors.params.api_key}</span>}
                        </div>
                        <Label className="bisheng-label text-sky-900 mt-4 block">Bing Search URL <span className="text-red-500">*</span></Label>
                        <div className="mt-3">
                            <Input
                                placeholder="https://api.bing.microsoft.com/v7.0/search"
                                value={currentParams.base_url || ''}
                                onChange={(e) => handleParamChange('base_url', e.target.value)}
                            />
                            {errors.params?.base_url && <span className="text-red-500 text-sm">Bing Search URL {errors.params.base_url}</span>}
                        </div>
                    </>
                );
            case 'bocha':
            case 'jina':
            case 'tavily':
                return (
                    <div>
                        <Label className="bisheng-label text-sky-900 mt-4 block">API Key <span className="text-red-500">*</span></Label>
                        <div className="mt-3">
                            <Input
                                type="password"
                                value={currentParams.api_key || ''}
                                onChange={(e) => handleParamChange('api_key', e.target.value)}
                            />
                            {errors.params?.api_key && <span className="text-red-500 text-sm">API Key {errors.params.api_key}</span>}
                        </div>
                    </div>
                );
            case 'serp':
                return (
                    <>
                        <Label className="bisheng-label text-sky-900 mt-4 block">API Key <span className="text-red-500">*</span></Label>
                        <div className="mt-3">
                            <Input
                                type="password"
                                value={currentParams.api_key || ''}
                                onChange={(e) => handleParamChange('api_key', e.target.value)}
                            />
                            {errors.params?.api_key && <span className="text-red-500 text-sm">API Key {errors.params.api_key}</span>}
                        </div>
                        <Label className="bisheng-label text-sky-900 mt-4 block">Engine <span className="text-red-500">*</span></Label>
                        <div className="mt-3">
                            <Input
                                value={currentParams.engine || ''}
                                onChange={(e) => handleParamChange('engine', e.target.value)}
                            />
                            {errors.params?.engine && <span className="text-red-500 text-sm">Engine {errors.params.engine}</span>}
                        </div>
                    </>
                );
            default:
                return null;
        }
    };

    return (
        <>
            <div className="mb-6 pr-96">
                <Label className="bisheng-label">联网搜索工具选择</Label>
                <div className="mt-3">
                    <Select
                        value={config.tool}
                        onValueChange={handleToolChange}
                    >
                        <SelectTrigger>
                            <SelectValue placeholder="选择搜索工具" />
                        </SelectTrigger>
                        <SelectContent>
                            <SelectGroup>
                                <SelectItem value="bing">Bing 搜索</SelectItem>
                                <SelectItem value="bocha">博查websearch</SelectItem>
                                <SelectItem value="jina">Jina 深度搜索</SelectItem>
                                <SelectItem value="serp">Serp Api</SelectItem>
                                <SelectItem value="tavily">Tavily</SelectItem>
                            </SelectGroup>
                        </SelectContent>
                    </Select>
                </div>
            </div>

            <div className="mb-6 pr-96">
                <Label className="bisheng-label mt-4">联网搜索工具配置</Label>
                {renderParams()}
            </div>

            <Label className="bisheng-label">联网搜索提示词</Label>
            <div className="mt-3">
                <Textarea
                    value={config.prompt}
                    className="min-h-48"
                    onChange={(e) => onChange('prompt', e.target.value)}
                />
            </div>
        </>
    );
};