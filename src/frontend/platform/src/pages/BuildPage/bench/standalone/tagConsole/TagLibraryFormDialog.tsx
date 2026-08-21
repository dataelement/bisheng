import { Button } from "@/components/bs-ui/button"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog"
import { Input, Textarea } from "@/components/bs-ui/input"
import { Label } from "@/components/bs-ui/label"
import { useToast } from "@/components/bs-ui/toast/use-toast"
import {
    addKnowledgeSpaceTagLibraryKnowledgesApi,
    createKnowledgeSpaceTagLibraryApi,
    getKnowledgeSpaceTagLibraryKnowledgesApi,
    removeKnowledgeSpaceTagLibraryKnowledgeApi,
    updateKnowledgeSpaceTagLibraryApi,
    type KnowledgeSpaceTagLibraryDetail,
    type TagLibraryBoundKnowledge,
} from "@/controllers/API/knowledgeSpaceTagLibrary"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { Plus, X } from "lucide-react"
import { useCallback, useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import { KnowledgePickerDialog } from "./KnowledgePickerDialog"

const NAME_MAX_LENGTH = 20

interface TagLibraryFormDialogProps {
    open: boolean
    mode: "create" | "edit"
    initial?: KnowledgeSpaceTagLibraryDetail | null
    onOpenChange: (open: boolean) => void
    onSaved: () => void
}

export function TagLibraryFormDialog({ open, mode, initial, onOpenChange, onSaved }: TagLibraryFormDialogProps) {
    const { t } = useTranslation()
    const { toast } = useToast()
    const [name, setName] = useState("")
    const [description, setDescription] = useState("")
    const [saving, setSaving] = useState(false)
    const [bound, setBound] = useState<TagLibraryBoundKnowledge[]>([])
    const [pickerOpen, setPickerOpen] = useState(false)
    const [linking, setLinking] = useState(false)

    const libraryId = mode === "edit" ? initial?.id ?? null : null

    const loadBound = useCallback(async () => {
        if (libraryId === null) {
            setBound([])
            return
        }
        const res = await captureAndAlertRequestErrorHoc(getKnowledgeSpaceTagLibraryKnowledgesApi(libraryId))
        setBound(res || [])
    }, [libraryId])

    useEffect(() => {
        if (!open) return
        setName(initial?.name || "")
        setDescription(initial?.description || "")
        void loadBound()
    }, [open, initial, loadBound])

    // Attaching writes straight through rather than waiting for 确定. The link is
    // its own record, not a field of the form, and holding it until save would
    // mean a cancel silently discarding something the user watched appear.
    const handleAddKnowledges = async (knowledgeIds: number[]) => {
        if (libraryId === null) return
        setLinking(true)
        const res = await captureAndAlertRequestErrorHoc(
            addKnowledgeSpaceTagLibraryKnowledgesApi(libraryId, knowledgeIds),
        )
        setLinking(false)
        if (!res) return
        setPickerOpen(false)
        await loadBound()
        onSaved()
    }

    const handleRemoveKnowledge = async (knowledgeId: number) => {
        if (libraryId === null) return
        const res = await captureAndAlertRequestErrorHoc(
            removeKnowledgeSpaceTagLibraryKnowledgeApi(libraryId, knowledgeId),
        )
        if (!res) return
        await loadBound()
        onSaved()
    }

    const handleSave = async () => {
        const trimmed = name.trim()
        if (!trimmed) {
            toast({ variant: "error", description: t("build.tagLibraryNameRequired", "标签库名称不能为空") })
            return
        }
        if (trimmed.length > NAME_MAX_LENGTH) {
            toast({ variant: "error", description: t("build.tagLibraryNameMaxLength", "标签库名称不能超过20个字符") })
            return
        }
        setSaving(true)
        const payload = { name: trimmed, description: description.trim() }
        const res = await captureAndAlertRequestErrorHoc(
            mode === "edit" && initial
                ? updateKnowledgeSpaceTagLibraryApi(initial.id, payload)
                : createKnowledgeSpaceTagLibraryApi({ ...payload, tags: [] }),
        )
        setSaving(false)
        if (!res) return
        toast({ variant: "success", description: t("build.saved", "已保存") })
        onOpenChange(false)
        onSaved()
    }

    return (
        <>
            <Dialog open={open} onOpenChange={onOpenChange}>
                <DialogContent className="gap-0 p-0 sm:max-w-[520px] bg-background-login">
                    <DialogHeader className="border-b border-[#EBECF0] px-6 py-4">
                        <DialogTitle>
                            {mode === "edit"
                                ? t("build.editTagLibrary", "编辑标签库")
                                : t("build.createTagLibrary", "新增标签库")}
                        </DialogTitle>
                    </DialogHeader>
                    <div className="space-y-5 px-6 py-5">
                        <div>
                            <Label className="bisheng-label">
                                {t("build.tagLibraryName", "标签库名称")}
                                <span className="bisheng-tip">*</span>
                            </Label>
                            <Input
                                className="mt-2"
                                value={name}
                                maxLength={NAME_MAX_LENGTH}
                                autoComplete="off"
                                placeholder={t("build.tagLibraryNamePlaceholder", "请输入标签库名称")}
                                onChange={(e) => setName(e.target.value)}
                            />
                        </div>
                        <div>
                            <Label className="bisheng-label">{t("build.description", "说明")}</Label>
                            <Textarea
                                className="mt-2 min-h-20"
                                value={description}
                                maxLength={1000}
                                onChange={(e) => setDescription(e.target.value)}
                            />
                        </div>
                        {/* Only on edit: a library has to exist before a space can point at it. */}
                        {mode === "edit" && (
                            <div>
                                <div className="flex items-center justify-between">
                                    <Label className="bisheng-label">
                                        {t("build.tagConsole.boundKnowledges", "关联知识库")}
                                    </Label>
                                    <Button
                                        variant="link"
                                        size="sm"
                                        className="h-auto px-0"
                                        onClick={() => setPickerOpen(true)}
                                    >
                                        <Plus className="mr-1 size-3.5" />
                                        {t("build.tagConsole.addKnowledge", "添加知识库")}
                                    </Button>
                                </div>
                                <div className="mt-2 max-h-40 overflow-y-auto rounded-md border border-[#E5E6EB] p-2">
                                    {!bound.length ? (
                                        <p className="py-4 text-center text-sm text-muted-foreground">
                                            {t("build.tagConsole.noBoundSpace", "暂无关联知识空间")}
                                        </p>
                                    ) : (
                                        bound.map((space) => (
                                            <div
                                                key={space.id}
                                                className="group flex items-center justify-between rounded px-2 py-1.5 text-sm hover:bg-[#F2F3F5]"
                                            >
                                                <span className="min-w-0 flex-1 truncate">{space.name}</span>
                                                <button
                                                    type="button"
                                                    className="ml-2 hidden shrink-0 group-hover:block"
                                                    onClick={() => void handleRemoveKnowledge(space.id)}
                                                >
                                                    <X className="size-3.5 text-muted-foreground hover:text-red-500" />
                                                </button>
                                            </div>
                                        ))
                                    )}
                                </div>
                            </div>
                        )}
                    </div>
                    <DialogFooter className="border-t border-[#EBECF0] px-6 py-3">
                        <Button variant="outline" className="px-8" onClick={() => onOpenChange(false)}>
                            {t("cancel", { ns: "bs" })}
                        </Button>
                        <Button className="px-8" disabled={saving} onClick={() => void handleSave()}>
                            {t("confirm", { ns: "bs" })}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
            <KnowledgePickerDialog
                open={pickerOpen}
                excludeIds={bound.map((space) => space.id)}
                saving={linking}
                onOpenChange={setPickerOpen}
                onConfirm={(ids) => void handleAddKnowledges(ids)}
            />
        </>
    )
}
