"use client"

import React, { createContext, useCallback, useContext, useState } from "react"

import { AlertCircle, Trash2, X } from "lucide-react"
import {
    AlertDialog,
    AlertDialogAction,
    AlertDialogCancel,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
} from "~/components/ui"
import { useLocalize } from "~/hooks"

interface ConfirmOptions {
    title?: string
    description?: string
    cancelText?: string
    confirmText?: string
    variant?: "default" | "destructive"
}

interface ConfirmContextType {
    confirm: (options: ConfirmOptions) => Promise<boolean>
}

export const ConfirmContext = createContext<ConfirmContextType | undefined>(undefined)

export const ConfirmProvider = ({ children }: { children: React.ReactNode }) => {
    const localize = useLocalize()
    const [open, setOpen] = useState(false)
    const [options, setOptions] = useState<ConfirmOptions>({})
    const [resolvePromise, setResolvePromise] = useState<(value: boolean) => void>()

    const confirm = useCallback((opts: ConfirmOptions) => {
        setOptions(opts)
        setOpen(true)
        return new Promise<boolean>((resolve) => {
            setResolvePromise(() => resolve)
        })
    }, [])

    const handleCancel = () => {
        setOpen(false)
        resolvePromise?.(false)
    }

    const handleConfirm = () => {
        setOpen(false)
        resolvePromise?.(true)
    }

    const isDestructive = options.variant === "destructive"

    return (
        <ConfirmContext.Provider value={{ confirm }}>
            {children}
            <AlertDialog open={open} onOpenChange={setOpen}>
                {isDestructive ? (
                    /* Destructive variant — matches the "删除操作确认" design. Screen-centered
                       (not a mobile bottom-sheet). Mobile: centered title + full-width equal
                       buttons. PC: left-aligned title + right-aligned hug buttons. */
                    <AlertDialogContent
                        onOpenAutoFocus={(e) => e.preventDefault()}
                        className="inset-0 m-auto flex h-fit max-h-[calc(100dvh-2rem)] max-w-[calc(100%-2rem)] flex-col items-center gap-4 rounded-[20px] border border-[#ebebeb] p-6 shadow-[0_0_16px_0_rgba(3,7,117,0.05)] sm:max-w-[400px] sm:rounded-[20px]"
                    >
                        <AlertDialogHeader className="w-full flex-row items-center justify-center gap-2 space-y-0 text-center sm:justify-start sm:text-left">
                            <Trash2 className="size-5 shrink-0 text-[#f53f3f]" />
                            <AlertDialogTitle className="text-base font-medium leading-6 text-[#f53f3f]">
                                {options.title || localize("com_knowledge.confirm_delete_title")}
                            </AlertDialogTitle>
                        </AlertDialogHeader>

                        <AlertDialogDescription className="w-full text-left text-sm leading-[22px] text-[#212121]">
                            {options.description}
                        </AlertDialogDescription>

                        <AlertDialogFooter className="w-full flex-row gap-2 sm:space-x-0">
                            <AlertDialogCancel
                                onClick={handleCancel}
                                className="mt-0 h-auto flex-1 rounded-[6px] border-[#ebecf0] bg-white/50 px-4 py-[5px] text-sm font-normal text-[#070038] backdrop-blur-[4px] hover:bg-white/70 sm:mt-0 sm:flex-none"
                            >
                                {options.cancelText || localize("com_knowledge.defer")}
                            </AlertDialogCancel>
                            <AlertDialogAction
                                onClick={handleConfirm}
                                className="h-auto flex-1 rounded-[6px] bg-[#f53f3f] px-4 py-[5px] text-sm font-normal text-white hover:bg-[#f53f3f]/90 sm:flex-none"
                            >
                                {options.confirmText || localize("com_knowledge.confirm_delete_action")}
                            </AlertDialogAction>
                        </AlertDialogFooter>
                    </AlertDialogContent>
                ) : (
                    <AlertDialogContent className="sm:max-w-[400px] p-6">
                        <button
                            onClick={handleCancel}
                            className="absolute right-4 top-4 opacity-70 hover:opacity-100 transition-opacity"
                        >
                            <X className="h-4 w-4 text-muted-foreground" />
                        </button>

                        <AlertDialogHeader className="relative pt-2">
                            <div className="absolute left-0 top-0">
                                <AlertCircle className="h-6 w-6 text-red-500" />
                            </div>
                            <AlertDialogTitle className="text-center text-xl font-medium">
                                {options.title || "提示"}
                            </AlertDialogTitle>
                            <AlertDialogDescription className="text-center py-4 text-base text-slate-600">
                                {options.description}
                            </AlertDialogDescription>
                        </AlertDialogHeader>

                        <AlertDialogFooter className="flex flex-row justify-center gap-4 sm:justify-center">
                            <AlertDialogCancel
                                onClick={handleCancel}
                                className="w-28 mt-0 border-slate-200 text-slate-600"
                            >
                                {options.cancelText || "取消"}
                            </AlertDialogCancel>
                            <AlertDialogAction
                                onClick={handleConfirm}
                                className={`w-28 bg-red-600 hover:bg-red-700`}
                            >
                                {options.confirmText || "确认"}
                            </AlertDialogAction>
                        </AlertDialogFooter>
                    </AlertDialogContent>
                )}
            </AlertDialog>
        </ConfirmContext.Provider>
    )
}

// export Hook
export const useConfirm = () => {
    const context = useContext(ConfirmContext)
    if (!context) throw new Error("useConfirm must be used within a ConfirmProvider")
    return context.confirm
}