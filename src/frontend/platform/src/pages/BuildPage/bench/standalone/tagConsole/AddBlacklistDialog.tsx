import { Button } from "@/components/bs-ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog"
import { Textarea } from "@/components/bs-ui/input"
import { Label } from "@/components/bs-ui/label"
import { useEffect, useState } from "react"
import { useTranslation } from "react-i18next"

interface AddBlacklistDialogProps {
    open: boolean
    saving: boolean
    onOpenChange: (open: boolean) => void
    onConfirm: (names: string[]) => Promise<string[]>
}

export function AddBlacklistDialog({ open, saving, onOpenChange, onConfirm }: AddBlacklistDialogProps) {
    const { t } = useTranslation()
    const [name, setName] = useState("")
    const names = [...new Set(name.split(/\r\n|\r|\n/).map((line) => line.trim()).filter(Boolean))]
    const hasLongName = names.some((item) => item.length > 64)

    const handleConfirm = async () => {
        if (saving || !names.length || hasLongName) return
        const remaining = await onConfirm(names)
        setName(remaining.join("\n"))
    }

    useEffect(() => {
        if (open) setName("")
    }, [open])

    return (
        <Dialog open={open} onOpenChange={(value) => !saving && onOpenChange(value)}>
            <DialogContent className="gap-0 p-0 sm:max-w-[560px] bg-background-login">
                <DialogHeader className="border-b border-[#EBECF0] px-6 py-4">
                    <DialogTitle>{t("build.tagConsole.blacklistAddTitle", "添加黑名单")}</DialogTitle>
                </DialogHeader>
                <div className="px-6 py-5">
                    <Label className="bisheng-label" htmlFor="blacklist-names">
                        {t("build.tagName", "标签名称")}
                        <span className="bisheng-tip">*</span>
                    </Label>
                    <Textarea
                        id="blacklist-names"
                        className="mt-2 min-h-[200px] resize-y"
                        rows={8}
                        value={name}
                        disabled={saving}
                        aria-invalid={hasLongName}
                        aria-describedby={hasLongName ? "blacklist-help blacklist-error" : "blacklist-help"}
                        autoComplete="off"
                        placeholder={t("build.tagConsole.blacklistNamesPlaceholder", "请输入标签名称，每行一条")}
                        onChange={(e) => setName(e.target.value)}
                    />
                    <DialogDescription className="mt-2 text-xs text-muted-foreground">
                        <span id="blacklist-help">
                            {t("build.tagConsole.blacklistNamesHelp", "每行一条，每条最多 64 个字符；自动忽略空行和重复项。")}
                        </span>
                    </DialogDescription>
                    {hasLongName && <p id="blacklist-error" role="alert" className="mt-2 text-xs text-red-500">
                        {t("build.tagConsole.blacklistNameTooLong", "存在超过 64 个字符的标签，请修改后提交。")}
                    </p>}
                </div>
                <DialogFooter className="border-t border-[#EBECF0] px-6 py-3">
                    <Button variant="outline" className="px-8" disabled={saving} onClick={() => onOpenChange(false)}>
                        {t("cancel", { ns: "bs" })}
                    </Button>
                    <Button
                        className="px-8"
                        disabled={saving || !names.length || hasLongName}
                        onClick={handleConfirm}
                    >
                        {t("confirm", { ns: "bs" })}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
