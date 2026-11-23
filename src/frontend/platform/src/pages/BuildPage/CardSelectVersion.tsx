import { useSelectLabels } from "@/components/bs-comp/formFields/useSelectLabels";
import { changeWorkflowCurrentVersion, getWorkFlowVersions } from "@/controllers/API/workflow";
import { showApiError } from "@/controllers/request";
import { Select, Tooltip } from "@bisheng/ui";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";

interface WorkflowVersion {
    id: string | number;
    name: string;
    is_current: number;
}

interface CardSelectVersionProps {
    showPop: boolean;
    data: { id: string };
    onLoadActions: () => Promise<{ actions: string[]; hasError: boolean }>;
}

export default function CardSelectVersion({ showPop, data, onLoadActions }: CardSelectVersionProps) {
    const { t } = useTranslation();
    const selectLabels = useSelectLabels();
    const [versions, setVersions] = useState<WorkflowVersion[] | null>(null);
    const [value, setValue] = useState<string | null>(null);
    const [loading, setLoading] = useState(false);
    const [canEdit, setCanEdit] = useState(false);
    const inFlight = useRef(false);

    const handleOpen = async (open: boolean) => {
        if (!open || inFlight.current) return;
        inFlight.current = true;
        setLoading(true);
        try {
            const result = await onLoadActions();
            if (result.hasError) return;
            setCanEdit(result.actions.includes("edit"));
            const response = await getWorkFlowVersions(data.id);
            const rows: WorkflowVersion[] = (response.data || []).filter(row => row.id != null && row.id !== "");
            setVersions(rows);
            setValue(String(rows.find(row => row.is_current === 1)?.id ?? "0"));
        } catch (error) {
            showApiError(error);
        } finally {
            setLoading(false);
            inFlight.current = false;
        }
    };

    const handleChange = async (id: string) => {
        if (!showPop || !canEdit || id === value || inFlight.current) return;
        inFlight.current = true;
        setLoading(true);
        try {
            await changeWorkflowCurrentVersion({ flow_id: data.id, version_id: Number(id) });
            setValue(id);
        } catch (error) {
            showApiError(error);
        } finally {
            inFlight.current = false;
            setLoading(false);
        }
    };

    const selector = <Select
        {...selectLabels}
        aria-label={t("skills.version")}
        size="small"
        className="w-[120px]"
        placeholder={t("skills.version")}
        options={versions?.length ? versions.map(row => ({ value: String(row.id), label: row.name })) : versions ? [{ value: "0", label: "v0" }] : []}
        value={value}
        loading={loading}
        onOpenChange={(open) => { void handleOpen(open); }}
        onChange={(next) => { if (next != null) void handleChange(String(next)); }}
    />;

    return <span className="inline-flex" onClick={event => event.stopPropagation()}>
        {showPop ? <Tooltip content={t("skills.chooseOnline")}>{selector}</Tooltip> : selector}
    </span>;
}
