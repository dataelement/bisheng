// src/features/chat-config/components/WebSearchConfig.tsx
import { Input, Textarea } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select";

export const WebSearchConfig = ({
    config,
    onChange,
    errors = {} // 接收错误信息
}: {
    config: {
        tool: string;
        bingKey: string;
        bingUrl: string;
        prompt: string;
    };
    onChange: (field: string, value: string) => void;
    errors?: Record<string, string>; // 新增错误类型
}) => (
    <>
        <div className="mb-6 pr-96">
            <Label className="bisheng-label">联网搜索工具选择</Label>
            <div className="mt-3">
                <Select
                    value={config.tool}
                    onValueChange={(val) => onChange('tool', val)}
                >
                    <SelectTrigger>
                        <SelectValue placeholder="选择搜索工具" />
                    </SelectTrigger>
                    <SelectContent>
                        <SelectGroup>
                            <SelectItem value="bing">Bing搜索</SelectItem>
                        </SelectGroup>
                    </SelectContent>
                </Select>
            </div>
        </div>

        <div className="mb-6 pr-96">
            <Label className="bisheng-label mt-4">联网搜索工具配置</Label>
            <Label className="bisheng-label text-sky-900 mt-4 block">Bing Subscription Key <span className="text-red-500">*</span></Label>
            <div className="mt-3">
                <Input
                    type="password"
                    value={config.bingKey}
                    onChange={(e) => onChange('bingKey', e.target.value)}
                />
                {errors.bingKey && <span className="text-red-500 text-sm">{errors.bingKey}</span>}
            </div>
            <Label className="bisheng-label text-sky-900 mt-4 block">Bing Search URL <span className="text-red-500">*</span></Label>
            <div className="mt-3">
                <Input
                    placeholder="https://api.bing.microsoft.com/v7.0/search"
                    value={config.bingUrl}
                    onChange={(e) => onChange('bingUrl', e.target.value)}
                />
                {errors.bingUrl && <span className="text-red-500 text-sm">{errors.bingUrl}</span>}
            </div>
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