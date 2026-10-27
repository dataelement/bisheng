import { Button, Dropdown, DropdownChevron, DropdownItem } from '@bisheng/ui';

import { Outlined } from "bisheng-icons";
import { KnowledgeTooltip } from "./KnowledgeTooltip";

import { cn } from "@/utils";
import { Link2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { knowledgeUploadCapabilities } from "../knowledgeUploadCapabilities";

interface AddKnowledgeFileMenuProps {
    disabled?: boolean;
    supportedFormatsLabel?: string;
    buttonClassName?: string;
    onUploadFile: () => void;
    onWebLink: () => void;
}

export default function AddKnowledgeFileMenu({
    disabled = false,
    supportedFormatsLabel,
    buttonClassName,
    onUploadFile,
    onWebLink,
}: AddKnowledgeFileMenuProps) {
    const { t } = useTranslation("knowledge");

    return (
        <Dropdown
            align="end"
            disabled={disabled}
            menu={
                <>
                    <DropdownItem icon={<Outlined.Upload />} onSelect={onUploadFile}>
                        {t("uploadFile")}
                        {supportedFormatsLabel ? (
                            <KnowledgeTooltip content={supportedFormatsLabel} side="left">
                                <span
                                    className="ml-1 inline-flex size-4 items-center justify-center align-middle text-text-3"
                                    onClick={(event) => event.stopPropagation()}
                                >
                                    <Outlined.Question className="size-3.5" />
                                </span>
                            </KnowledgeTooltip>
                        ) : null}
                    </DropdownItem>
                    {knowledgeUploadCapabilities.webLink && (
                        <DropdownItem icon={<Link2 />} onSelect={onWebLink}>
                            {t("webLink")}
                        </DropdownItem>
                    )}
                </>
            }
        >
            <Button className={cn("h-9 gap-2 px-4 md:px-6", buttonClassName)}>
                {t("add")}
                <DropdownChevron className="size-4" />
            </Button>
        </Dropdown>
    );
}
