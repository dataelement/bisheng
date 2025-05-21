import { Input, Textarea } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select";

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
    // 处理参数变化的通用方法
    const handleParamChange = (field: string, value: string) => {
        onChange('params', { ...config.params, [field]: value });
    };

    // 根据当前工具渲染参数配置
    const renderParams = () => {
        switch (config.tool) {
            case 'bing':
                return (
                    <>
                        <Label className="bisheng-label text-sky-900 mt-4 block">Bing Subscription Key <span className="text-red-500">*</span></Label>
                        <div className="mt-3">
                            <Input
                                type="password"
                                value={config.params.api_key || ''}
                                onChange={(e) => handleParamChange('api_key', e.target.value)}
                            />
                            {errors.params?.api_key && <span className="text-red-500 text-sm">{errors.params.api_key}</span>}
                        </div>
                        <Label className="bisheng-label text-sky-900 mt-4 block">Bing Search URL <span className="text-red-500">*</span></Label>
                        <div className="mt-3">
                            <Input
                                placeholder="https://api.bing.microsoft.com/v7.0/search"
                                value={config.params.base_url || ''}
                                onChange={(e) => handleParamChange('base_url', e.target.value)}
                            />
                            {errors.params?.base_url && <span className="text-red-500 text-sm">{errors.params.base_url}</span>}
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
                                value={config.params.api_key || ''}
                                onChange={(e) => handleParamChange('api_key', e.target.value)}
                            />
                            {errors.params?.api_key && <span className="text-red-500 text-sm">{errors.params.api_key}</span>}
                        </div>
                    </div>
                );
            case 'searp':
                return (
                    <>
                        <Label className="bisheng-label text-sky-900 mt-4 block">API Key <span className="text-red-500">*</span></Label>
                        <div className="mt-3">
                            <Input
                                type="password"
                                value={config.params.api_key || ''}
                                onChange={(e) => handleParamChange('api_key', e.target.value)}
                            />
                            {errors.params?.api_key && <span className="text-red-500 text-sm">{errors.params.api_key}</span>}
                        </div>
                        <Label className="bisheng-label text-sky-900 mt-4 block">Engine <span className="text-red-500">*</span></Label>
                        <div className="mt-3">
                            <Input
                                value={config.params.engine || ''}
                                onChange={(e) => handleParamChange('engine', e.target.value)}
                            />
                            {errors.params?.engine && <span className="text-red-500 text-sm">{errors.params.engine}</span>}
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
                        onValueChange={(val) => {
                            onChange('tool', val);
                            handleParamChange('api_key', '')
                        }}
                    >
                        <SelectTrigger>
                            <SelectValue placeholder="选择搜索工具" />
                        </SelectTrigger>
                        <SelectContent>
                            <SelectGroup>
                                <SelectItem value="bing">Bing 搜索</SelectItem>
                                <SelectItem value="bocha">博查websearch</SelectItem>
                                <SelectItem value="jina">Jina 深度搜索</SelectItem>
                                <SelectItem value="searp">Searp Api</SelectItem>
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