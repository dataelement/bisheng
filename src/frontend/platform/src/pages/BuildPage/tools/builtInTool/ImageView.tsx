import { Button, Select } from '@bisheng/ui';

import { DialogClose, DialogFooter } from "@/components/bs-ui/dialog";
import { Label } from "@/components/bs-ui/label";
import { useSelectLabels } from "@/components/bs-comp/formFields/useSelectLabels";
import { getLinsightModelConfig } from "@/controllers/API/finetune";
import { useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

interface VisualModel {
    id: string;
    name?: string;
    displayName?: string;
    visual?: boolean;
}

interface ImageViewFormProps {
    formData?: { model_id?: string };
    onSubmit: (data: { model_id: string }) => void;
}

export function ImageViewForm({ formData = {}, onSubmit }: ImageViewFormProps) {
    const { t } = useTranslation("tool");
    const [modelId, setModelId] = useState(formData.model_id || "");
    const [models, setModels] = useState<VisualModel[]>([]);
    const selectLabels = useSelectLabels();

    useEffect(() => {
        let cancelled = false;
        getLinsightModelConfig()
            .then((config) => {
                if (cancelled) return;
                const visual = (config?.models || []).filter(
                    (model: VisualModel) => model?.visual && model.id
                );
                setModels(visual);
            })
            .catch(() => {
                if (!cancelled) setModels([]);
            });
        return () => {
            cancelled = true;
        };
    }, []);

    const selected = models.some((model) => String(model.id) === String(modelId)) ? String(modelId) : "";

    const handleSubmit = (event: FormEvent) => {
        event.preventDefault();
        if (!selected) return;
        onSubmit({ model_id: selected });
    };

    return (
        <form onSubmit={handleSubmit} className="flex flex-col gap-6">
            <div className="flex flex-col gap-2">
                <Label>{t("imageViewModelLabel")}</Label>
                <Select
                    {...selectLabels}
                    aria-label={t("imageViewModelLabel")}
                    placeholder={t("pleaseSelect")}
                    options={models.map((model) => ({
                        value: String(model.id),
                        label: model.displayName || model.name || String(model.id),
                    }))}
                    value={selected || null}
                    onChange={(value) => {
                        if (value != null) setModelId(String(value));
                    }}
                />
                {models.length === 0 ? (
                    <p className="text-xs text-muted-foreground">{t("imageViewNoVisualModel")}</p>
                ) : null}
            </div>
            <DialogFooter>
                <DialogClose>
                    <Button variant="outlined" type="button" color="default">
                        {t("cancel", { ns: "bs" })}
                    </Button>
                </DialogClose>
                <Button type="submit" disabled={!selected}>
                    {t("save", { ns: "bs" })}
                </Button>
            </DialogFooter>
        </form>
    );
}
