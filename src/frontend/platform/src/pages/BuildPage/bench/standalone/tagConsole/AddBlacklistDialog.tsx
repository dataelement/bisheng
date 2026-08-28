import { Button } from "@/components/bs-ui/button"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog"
import { Input } from "@/components/bs-ui/input"
import { Label } from "@/components/bs-ui/label"
import { useEffect, useState } from "react"
import { useTranslation } from "react-i18next"

interface AddBlacklistDialogProps {
    open: boolean
    saving: boolean
    onOpenChange: (open: boolean) => void
    onConfirm: (name: string) => void
}

export function AddBlacklistDialog({ open, saving, onOpenChange, onConfirm }: AddBlacklistDialogProps) {
    const { t } = useTranslation()
    const [name, setName] = useState("")

    useEffect(() => {
        if (open) setName("")
    }, [open])

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="gap-0 p-0 sm:max-w-[460px] bg-background-login">
                <DialogHeader className="border-b border-[#EBECF0] px-6 py-4">
                    <DialogTitle>{t("build.tagConsole.blacklistAddTitle", "添加黑名单")}</DialogTitle>
                </DialogHeader>
                <div className="px-6 py-5">
                    <Label className="bisheng-label">
                        {t("build.tagName", "标签名称")}
                        <span className="bisheng-tip">*</span>
                    </Label>
                    <Input
                        className="mt-2"
                        value={name}
                        maxLength={64}
                        autoComplete="off"
                        placeholder={t("build.tagConsole.tagNamePlaceholder", "请输入标签名称")}
                        onChange={(e) => setName(e.target.value)}
                        onKeyDown={(e) => {
                            if (e.key === "Enter" && name.trim() && !saving) {
                                onConfirm(name.trim())
                            }
                        }}
                    />
                </div>
                <DialogFooter className="border-t border-[#EBECF0] px-6 py-3">
                    <Button variant="outline" className="px-8" onClick={() => onOpenChange(false)}>
                        {t("cancel", { ns: "bs" })}
                    </Button>
                    <Button
                        className="px-8"
                        disabled={saving || !name.trim()}
                        onClick={() => onConfirm(name.trim())}
                    >
                        {t("confirm", { ns: "bs" })}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
