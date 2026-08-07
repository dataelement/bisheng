import { Button } from "@/components/bs-ui/button"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog"
import { Input } from "@/components/bs-ui/input"
import { Label } from "@/components/bs-ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select"
import type { KnowledgeSpaceTagLibraryListItem } from "@/controllers/API/knowledgeSpaceTagLibrary"
import { useEffect, useState } from "react"
import { useTranslation } from "react-i18next"

interface AddTagDialogProps {
    open: boolean
    saving: boolean
    libraries: KnowledgeSpaceTagLibraryListItem[]
    /** Preselects the library when exactly one is picked on the left. */
    defaultLibraryId?: number | null
    onOpenChange: (open: boolean) => void
    onConfirm: (tagName: string, libraryId: number) => void
}

export function AddTagDialog({
    open,
    saving,
    libraries,
    defaultLibraryId,
    onOpenChange,
    onConfirm,
}: AddTagDialogProps) {
    const { t } = useTranslation()
    const [tagName, setTagName] = useState("")
    const [libraryId, setLibraryId] = useState("")

    useEffect(() => {
        if (!open) return
        setTagName("")
        setLibraryId(defaultLibraryId ? String(defaultLibraryId) : "")
    }, [open, defaultLibraryId])

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="gap-0 p-0 sm:max-w-[460px] bg-background-login">
                <DialogHeader className="border-b border-[#EBECF0] px-6 py-4">
                    <DialogTitle>{t("build.addTag", "添加")}</DialogTitle>
                </DialogHeader>
                <div className="space-y-5 px-6 py-5">
                    <div>
                        <Label className="bisheng-label">
                            {t("build.tagName", "标签名称")}
                            <span className="bisheng-tip">*</span>
                        </Label>
                        <Input
                            className="mt-2"
                            value={tagName}
                            maxLength={64}
                            autoComplete="off"
                            onChange={(e) => setTagName(e.target.value)}
                        />
                    </div>
                    <div>
                        <Label className="bisheng-label">
                            {t("build.reviewTagSelectLibrary", "选择标签库")}
                            <span className="bisheng-tip">*</span>
                        </Label>
                        <Select value={libraryId} onValueChange={setLibraryId}>
                            <SelectTrigger className="mt-2">
                                <SelectValue
                                    placeholder={t("build.reviewTagSelectLibraryPlaceholder", "请选择标签库")}
                                />
                            </SelectTrigger>
                            <SelectContent>
                                {libraries.map((library) => (
                                    <SelectItem key={library.id} value={String(library.id)}>
                                        {library.name}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    </div>
                </div>
                <DialogFooter className="border-t border-[#EBECF0] px-6 py-3">
                    <Button variant="outline" className="px-8" onClick={() => onOpenChange(false)}>
                        {t("cancel", { ns: "bs" })}
                    </Button>
                    <Button
                        className="px-8"
                        disabled={saving || !tagName.trim() || !libraryId}
                        onClick={() => onConfirm(tagName.trim(), Number(libraryId))}
                    >
                        {t("confirm", { ns: "bs" })}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
