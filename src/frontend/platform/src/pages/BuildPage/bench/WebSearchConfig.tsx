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
    
    console.log(config,88);
    
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
        console.log(config,333);
        if (config.tool && config.params) {
            setToolsParams(prev => ({
                ...prev,
                [config.tool]: { ...prev[config.tool], ...config.params }
            }));
        }
    }, [config]);

    // Handle parameter changes for the current tool




    // Render parameters based on current tool


    return (
        <>
      

            <Label className="bisheng-label">联网搜索提示词</Label>
            <div className="mt-3">
                <Textarea
                    value={config.prompt||config}
                    className="min-h-48"
                    onChange={(e) => onChange('prompt', e.target.value)}
                />
            </div>
        </>
    );
};