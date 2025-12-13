import { Textarea } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

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
    const { t } = useTranslation();

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

    return (
        <>
            <Label className="bisheng-label">{t('bench.webSearchPrompt')}</Label>
            <div className="mt-3">
                <Textarea
                    value={config.prompt || config}
                    className="min-h-48"
                    onChange={(e) => onChange('prompt', e.target.value)}
                />
            </div>
        </>
    );
};