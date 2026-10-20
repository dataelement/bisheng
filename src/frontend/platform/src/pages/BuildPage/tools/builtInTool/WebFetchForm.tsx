import { Button } from '@bisheng/ui';

import { DialogClose, DialogFooter } from "@/components/bs-ui/dialog";
import { Label } from "@/components/bs-ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select";
import { useState, type ChangeEvent, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { InputField } from "./InputField";

// Engine defaults; an empty base_url falls back to the backend's endpoint.
const ENGINE_DEFAULT_BASE_URL: Record<string, string> = {
    deepseek: "https://api.deepseek.com/v1/tools/fetch",
};
const DEFAULT_ENGINE = "deepseek";
const ENGINE_OPTIONS = [{ value: "deepseek", labelKey: "webFetchEngineDeepseek" }];
const DEFAULT_MAX_CHARS = 20000;
const MIN_MAX_CHARS = 1000;
const MAX_MAX_CHARS = 200000;

interface EngineConfig {
    api_key?: string;
    base_url?: string;
}

export interface WebFetchConfig {
    type: string;
    config: Record<string, EngineConfig>;
    max_chars: number;
}

interface WebFetchFormProps {
    formData?: Partial<WebFetchConfig> | null;
    onSubmit: (config: WebFetchConfig) => void;
}

type FormErrors = Partial<Record<"api_key" | "max_chars", string>>;

export function WebFetchForm({ formData, onSubmit }: WebFetchFormProps) {
    const { t } = useTranslation("tool");
    const [engine, setEngine] = useState(formData?.type || DEFAULT_ENGINE);
    const [engineConfigs, setEngineConfigs] = useState<Record<string, EngineConfig>>(formData?.config || {});
    const [maxChars, setMaxChars] = useState(String(formData?.max_chars ?? DEFAULT_MAX_CHARS));
    const [errors, setErrors] = useState<FormErrors>({});

    const current = engineConfigs[engine] || {};

    const handleEngineChange = (value: string) => {
        setEngine(value);
        setErrors({});
    };

    const handleParamChange = (event: ChangeEvent<HTMLInputElement>) => {
        const { name, value } = event.target;
        setEngineConfigs((prev) => ({ ...prev, [engine]: { ...prev[engine], [name]: value } }));
        setErrors((prev) => ({ ...prev, [name]: undefined }));
    };

    const handleMaxCharsChange = (event: ChangeEvent<HTMLInputElement>) => {
        setMaxChars(event.target.value);
        setErrors((prev) => ({ ...prev, max_chars: undefined }));
    };

    const handleSubmit = (event: FormEvent) => {
        event.preventDefault();
        const nextErrors: FormErrors = {};
        if (!current.api_key) nextErrors.api_key = t("fieldCannotBeEmpty", { label: "API Key" });
        const parsedMaxChars = Number(maxChars);
        if (!Number.isInteger(parsedMaxChars) || parsedMaxChars < MIN_MAX_CHARS || parsedMaxChars > MAX_MAX_CHARS) {
            nextErrors.max_chars = t("webFetchMaxCharsRange");
        }
        if (Object.keys(nextErrors).length > 0) {
            setErrors(nextErrors);
            return;
        }
        onSubmit({
            type: engine,
            config: { ...engineConfigs, [engine]: { api_key: current.api_key, base_url: current.base_url || "" } },
            max_chars: parsedMaxChars,
        });
    };

    return (
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <div>
                <Label htmlFor="web-fetch-engine" className="bisheng-label">{t("webFetchEngine")}</Label>
                <Select value={engine} onValueChange={(value) => value && handleEngineChange(value)}>
                    <SelectTrigger id="web-fetch-engine" className="h-8 mt-2">
                        <SelectValue placeholder={t("pleaseSelect")} />
                    </SelectTrigger>
                    <SelectContent>
                        {ENGINE_OPTIONS.map((option) => (
                            <SelectItem key={option.value} value={option.value}>
                                {t(option.labelKey)}
                            </SelectItem>
                        ))}
                    </SelectContent>
                </Select>
            </div>
            <InputField
                required
                label="API Key"
                type="password"
                id={`${engine}-fetch-api-key`}
                name="api_key"
                value={current.api_key || ""}
                onChange={handleParamChange}
                error={errors.api_key}
            />
            <InputField
                label="Base URL"
                id={`${engine}-fetch-base-url`}
                name="base_url"
                value={current.base_url || ""}
                placeholder={ENGINE_DEFAULT_BASE_URL[engine]}
                onChange={handleParamChange}
            />
            <InputField
                required
                label={t("webFetchMaxChars")}
                tooltip={t("webFetchMaxCharsHint")}
                type="number"
                id="web-fetch-max-chars"
                name="max_chars"
                value={maxChars}
                onChange={handleMaxCharsChange}
                error={errors.max_chars}
            />
            <DialogFooter>
                <DialogClose>
                    <Button variant="outlined" className="px-11" type="button" color="default">
                        {t("cancel", { ns: "bs" })}
                    </Button>
                </DialogClose>
                <Button className="px-11" type="submit">
                    {t("save", { ns: "bs" })}
                </Button>
            </DialogFooter>
        </form>
    );
}
