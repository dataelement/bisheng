import { Tag } from "@bisheng/ui";
import { useTranslation } from "react-i18next";

interface FileAbnormalStatusCellProps {
    hasAbnormalFiles?: boolean;
}

export function FileAbnormalStatusCell({ hasAbnormalFiles }: FileAbnormalStatusCellProps) {
    const { t } = useTranslation("knowledge");
    if (!hasAbnormalFiles) {
        return null;
    }
    return (
        <Tag size="small" dot color="danger" className="shrink-0 whitespace-nowrap">
            {t("fileStatusAbnormal")}
        </Tag>
    );
}
