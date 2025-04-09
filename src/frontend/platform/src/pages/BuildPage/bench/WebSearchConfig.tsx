// src/features/chat-config/components/WebSearchConfig.tsx
import { Input, Textarea } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select";

export const WebSearchConfig = ({
    config,
    onChange,
}: {
    config: {
        tool: string;
        bingKey: string;
        bingUrl: string;
        prompt: string;
    };
    onChange: (field: string, value: string) => void;
}) => (
    <>
        <div className="mb-6">
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

        <div className="mb-6">
            <Label className="bisheng-label mt-4">联网搜索工具配置</Label>
            <Label className="bisheng-label text-sky-900 mt-4 block">Bing Subscription Key <span className="text-red-500">*</span></Label>
            <div className="mt-3">
                <Input
                    value={config.bingKey}
                    onChange={(e) => onChange('bingKey', e.target.value)}
                />
            </div>
            <Label className="bisheng-label text-sky-900 mt-4 block">Bing Search URL <span className="text-red-500">*</span></Label>
            <div className="mt-3">
                <Input
                    placeholder="https://api.bing.microsoft.com/v7.0/search"
                    value={config.bingUrl}
                    onChange={(e) => onChange('bingUrl', e.target.value)}
                />
            </div>
        </div>

        <Label className="bisheng-label">联网搜索提示词</Label>
        <div className="mt-3">
            <Textarea
                value={config.prompt}
                onChange={(e) => onChange('prompt', e.target.value)}
            />
        </div>
    </>
);