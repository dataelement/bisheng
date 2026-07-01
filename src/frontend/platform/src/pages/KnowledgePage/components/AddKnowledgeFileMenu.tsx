import { Button } from "@/components/bs-ui/button";
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from "@/components/bs-ui/dropdownMenu";
import Tip from "@/components/bs-ui/tooltip/tip";
import { cn } from "@/utils";
import { ChevronDown, CircleHelp, Link2, Upload } from "lucide-react";
import { useTranslation } from "react-i18next";

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
        <DropdownMenu>
            <DropdownMenuTrigger asChild disabled={disabled}>
                <Button className={cn("h-9 gap-2 px-4 md:px-6", buttonClassName)}>
                    {t("add", { defaultValue: "新增" })}
                    <ChevronDown className="size-4" />
                </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="min-w-[140px] bg-white p-1">
                <DropdownMenuItem
                    className="h-9 cursor-pointer gap-2 px-3"
                    onSelect={onUploadFile}
                >
                    <Upload className="size-4" />
                    <span>{t("uploadFile")}</span>
                    {supportedFormatsLabel ? (
                        <Tip content={supportedFormatsLabel} side="left">
                            <span
                                className="ml-auto inline-flex size-4 items-center justify-center text-[#8a94a6]"
                                onClick={(event) => event.stopPropagation()}
                            >
                                <CircleHelp className="size-3.5" />
                            </span>
                        </Tip>
                    ) : null}
                </DropdownMenuItem>
                <DropdownMenuItem
                    className="h-9 cursor-pointer gap-2 px-3"
                    onSelect={onWebLink}
                >
                    <Link2 className="size-4" />
                    <span>{t("webLink", { defaultValue: "网页链接" })}</span>
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    );
}
