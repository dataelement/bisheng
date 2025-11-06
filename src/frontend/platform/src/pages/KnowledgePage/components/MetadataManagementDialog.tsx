"use client"

import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm"
import { Button } from "@/components/bs-ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog"
import { Input } from "@/components/bs-ui/input"
import { AlertCircle, Edit2, Plus, Trash2 } from "lucide-react"
import { useCallback, useState } from "react"

type MetadataType = "String" | "Number" | "Time"

interface Metadata {
    id: string
    name: string
    type: MetadataType
    createdAt: Date
    updatedAt: Date
}

interface BuiltInMetadata {
    name: string
    type: MetadataType
    description: string
}

const BUILT_IN_METADATA: BuiltInMetadata[] = [
    { name: "document_id", type: "Number", description: "系统文档id值，全局唯一" },
    { name: "document_name", type: "String", description: "知识库文档名称，知识库唯一" },
    { name: "upload_time", type: "Time", description: "文档上传时间" },
    { name: "update_time", type: "Time", description: "文档最后一次更新时间" },
    { name: "uploader", type: "String", description: "文档上传者" },
    { name: "updater", type: "String", description: "文档最后一次更新者" },
]

const TYPE_ICONS = {
    String: "📄",
    Number: "#",
    Time: "⏱️",
}

interface MetadataManagementDialogProps {
    open: boolean
    onOpenChange: (open: boolean) => void
    onSave?: (metadata: Metadata[]) => void
    hasManagePermission?: boolean
}

export function MetadataManagementDialog({
    open,
    onOpenChange,
    onSave,
    hasManagePermission = true
}: MetadataManagementDialogProps) {

    const [metadataList, setMetadataList] = useState<Metadata[]>([])
    const [dialogMode, setDialogMode] = useState<"main" | "create" | "rename">("main")
    const [isLoading, setIsLoading] = useState(false)
    const [selectedMetadata, setSelectedMetadata] = useState<Metadata | null>(null)
    const [newName, setNewName] = useState("")
    const [newType, setNewType] = useState<MetadataType>("String")
    const [error, setError] = useState("")

    const validateName = (name: string): { valid: boolean; error?: string } => {
        if (!name || name.trim().length === 0) {
            return { valid: false, error: "名称不能为空。" }
        }
        if (name.length > 255) {
            return { valid: false, error: "名称不能超过255个字符。" }
        }
        if (!/^[a-z][a-z0-9_]*$/.test(name)) {
            return { valid: false, error: "必须以小写字母开头，且只能包含小写字母、数字和下划线。" }
        }
        const nameExists = metadataList.some((m) => m.name === name && m.id !== selectedMetadata?.id)
        if (nameExists) {
            return { valid: false, error: "元数据名已存在。" }
        }
        return { valid: true }
    }

    const handleCreateClick = useCallback(() => {
        setDialogMode("create")
        setNewType("String")
        setNewName("")
        setError("")
    }, [])

    const handleCreateSave = useCallback(() => {
        const validation = validateName(newName)
        if (!validation.valid) {
            setError(validation.error || "输入不符合规范")
            return
        }

        setIsLoading(true)
        // 模拟API调用延迟
        setTimeout(() => {
            const newMetadata: Metadata = {
                id: `meta_${Date.now()}`,
                name: newName,
                type: newType,
                createdAt: new Date(),
                updatedAt: new Date(),
            }
            setMetadataList((prev) => [newMetadata, ...prev])
            setDialogMode("main")
            setIsLoading(false)
            setError("")
        }, 500)
    }, [newName, newType, metadataList])

    const handleEditClick = useCallback((metadata: Metadata) => {
        setSelectedMetadata(metadata)
        setNewName(metadata.name)
        setDialogMode("rename")
        setError("")
    }, [])

    const handleRenameSave = useCallback(() => {
        const validation = validateName(newName)
        if (!validation.valid) {
            setError(validation.error || "输入不符合规范")
            return
        }

        setIsLoading(true)
        // 模拟API调用延迟
        setTimeout(() => {
            setMetadataList((prev) =>
                prev.map((m) => (m.id === selectedMetadata?.id ? { ...m, name: newName, updatedAt: new Date() } : m)),
            )
            setDialogMode("main")
            setIsLoading(false)
            setError("")
        }, 500)
    }, [newName, selectedMetadata])

    const handleDelete = useCallback((metadata: Metadata) => {
        bsConfirm({
            desc: "确认删除？",
            okTxt: "删除",
            onOk(next: () => void) {
                setIsLoading(true)
                // 模拟API调用延迟
                setTimeout(() => {
                    setMetadataList((prev) => prev.filter((m) => m.id !== metadata.id))
                    setIsLoading(false)
                    next()
                }, 500)
            },
        })
    }, [])

    const handleMainSave = useCallback(() => {
        setIsLoading(true)
        // 模拟API调用延迟
        setTimeout(() => {
            // if (onSave) {
            //     onSave(metadataList)
            // }
            setIsLoading(false)
            onOpenChange(false)
        }, 500)
    }, [metadataList, onSave, onOpenChange])

    const sortedMetadata = [...metadataList].sort((a, b) => b.updatedAt.getTime() - a.updatedAt.getTime())

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
                {dialogMode === "main" && (
                    <>
                        <DialogHeader>
                            <DialogTitle>元数据</DialogTitle>
                        </DialogHeader>
                        <div className="space-y-6">
                            {/* 新建按钮 */}
                            <button
                                onClick={handleCreateClick}
                                disabled={!hasManagePermission}
                                className="w-full flex items-center justify-center gap-2 py-3 rounded-lg bg-gray-100 hover:bg-gray-200 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                            >
                                <Plus size={20} />
                                <span>新建元数据</span>
                            </button>

                            {/* 自定义元数据列表 */}
                            <div className="space-y-2">
                                {sortedMetadata.map((metadata) => (
                                    <div
                                        key={metadata.id}
                                        className="flex items-center justify-between p-3 bg-gray-50 rounded-lg hover:bg-gray-100 transition-colors"
                                    >
                                        <div className="flex items-center gap-3 flex-1">
                                            <span className="text-lg">{TYPE_ICONS[metadata.type]}</span>
                                            <span className="text-sm text-gray-500">{metadata.type}</span>
                                            <span className="font-medium">{metadata.name}</span>
                                        </div>
                                        <div className="flex gap-2">
                                            <button
                                                onClick={() => handleEditClick(metadata)}
                                                disabled={!hasManagePermission}
                                                className="p-2 hover:bg-gray-200 rounded disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                                            >
                                                <Edit2 size={18} />
                                            </button>
                                            <button
                                                onClick={() => handleDelete(metadata)}
                                                disabled={!hasManagePermission}
                                                className="p-2 hover:bg-gray-200 rounded disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                                            >
                                                <Trash2 size={18} />
                                            </button>
                                        </div>
                                    </div>
                                ))}
                            </div>

                            {/* 内置元数据 */}
                            <div className="space-y-3">
                                <div className="flex items-center gap-2">
                                    <h3 className="font-semibold">内置元数据</h3>
                                    <div className="group relative cursor-help">
                                        <span className="text-gray-400">?</span>
                                        <div className="absolute bottom-full left-0 mb-2 hidden group-hover:block bg-gray-800 text-white text-sm rounded px-2 py-1 whitespace-nowrap z-10">
                                            内置元数据是系统预定义的元数据
                                        </div>
                                    </div>
                                </div>
                                <div className="space-y-2">
                                    {BUILT_IN_METADATA.map((metadata) => (
                                        <div key={metadata.name} className="flex items-center gap-3 p-3 bg-gray-50 rounded-lg">
                                            <span className="text-lg">{TYPE_ICONS[metadata.type]}</span>
                                            <span className="text-sm text-gray-500">{metadata.type}</span>
                                            <span className="font-medium">{metadata.name}</span>
                                        </div>
                                    ))}
                                </div>
                            </div>

                            {/* 按钮 */}
                            <div className="flex justify-end gap-3 pt-4">
                                <Button variant="outline" onClick={() => onOpenChange(false)}>
                                    取消
                                </Button>
                                <Button onClick={handleMainSave} disabled={isLoading} className="bg-blue-600 hover:bg-blue-700">
                                    {isLoading ? "保存中..." : "保存"}
                                </Button>
                            </div>
                        </div>
                    </>
                )}

                {dialogMode === "create" && (
                    <>
                        <DialogHeader>
                            <DialogTitle>新建元数据</DialogTitle>
                            <DialogDescription>请定义新元数据的类型和名称。</DialogDescription>
                        </DialogHeader>
                        <div className="space-y-4">
                            {/* 类型选择 */}
                            <div className="space-y-2">
                                <label className="block font-medium">类型</label>
                                <div className="flex gap-2">
                                    {(["String", "Number", "Time"] as MetadataType[]).map((type) => (
                                        <button
                                            key={type}
                                            onClick={() => setNewType(type)}
                                            className={`flex-1 py-2 px-4 rounded font-medium transition-colors ${newType === type ? "bg-blue-600 text-white" : "bg-gray-200 text-gray-700 hover:bg-gray-300"
                                                }`}
                                        >
                                            {type}
                                        </button>
                                    ))}
                                </div>
                            </div>

                            {/* 名称输入 */}
                            <div className="space-y-2">
                                <label className="block font-medium">名称</label>
                                <Input
                                    value={newName}
                                    onChange={(e) => {
                                        setNewName(e.target.value)
                                        if (error) setError("")
                                    }}
                                    placeholder="请输入"
                                    className={error ? "border-red-500 border-2" : ""}
                                />
                                {error && (
                                    <div className="flex items-center gap-2 text-red-500 text-sm">
                                        <AlertCircle size={16} />
                                        <span>{error}</span>
                                    </div>
                                )}
                            </div>

                            {/* 按钮 */}
                            <div className="flex justify-end gap-3 pt-4">
                                <Button variant="outline" onClick={() => setDialogMode("main")}>
                                    取消
                                </Button>
                                <Button onClick={handleCreateSave} disabled={isLoading} className="bg-blue-600 hover:bg-blue-700">
                                    {isLoading ? "保存中..." : "保存"}
                                </Button>
                            </div>
                        </div>
                    </>
                )}

                {dialogMode === "rename" && (
                    <>
                        <DialogHeader>
                            <DialogTitle>重命名</DialogTitle>
                            <DialogDescription>请输入新的名称</DialogDescription>
                        </DialogHeader>
                        <div className="space-y-4">
                            {/* 名称输入 */}
                            <div className="space-y-2">
                                <label className="block font-medium">名称</label>
                                <Input
                                    value={newName}
                                    onChange={(e) => {
                                        setNewName(e.target.value)
                                        if (error) setError("")
                                    }}
                                    placeholder="请输入"
                                    className={error ? "border-red-500 border-2" : ""}
                                />
                                {error && (
                                    <div className="flex items-center gap-2 text-red-500 text-sm">
                                        <AlertCircle size={16} />
                                        <span>{error}</span>
                                    </div>
                                )}
                            </div>

                            {/* 按钮 */}
                            <div className="flex justify-end gap-3 pt-4">
                                <Button variant="outline" onClick={() => setDialogMode("main")}>
                                    取消
                                </Button>
                                <Button onClick={handleRenameSave} disabled={isLoading} className="bg-blue-600 hover:bg-blue-700">
                                    {isLoading ? "保存中..." : "保存"}
                                </Button>
                            </div>
                        </div>
                    </>
                )}
            </DialogContent>
        </Dialog>
    )
}
