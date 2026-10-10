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
        <div className="flex items-center gap-2 cursor-default">
            <span className="size-[6px] rounded-full bg-red-500"></span>
            <span className="font-[500] text-[14px] leading-[100%] text-red-500">
                {t("fileStatusAbnormal")}
            </span>
        </div>
    );
}
