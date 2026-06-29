"use client"

import React, { createContext, useCallback, useContext, useRef, useState } from "react"

import { AlertCircle, Trash2 } from "lucide-react"
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
    /** Override the title icon in the destructive variant (defaults to Trash2). */
    icon?: React.ReactNode
}

interface ConfirmContextType {
    confirm: (options: ConfirmOptions) => Promise<boolean>
}

export const ConfirmContext = createContext<ConfirmContextType | undefined>(undefined)

export const ConfirmProvider = ({ children }: { children: React.ReactNode }) => {
    const localize = useLocalize()
    const [open, setOpen] = useState(false)
    const [options, setOptions] = useState<ConfirmOptions>({})
    // The pending promise resolver and the result chosen by a button. Held in
    // refs so that every close path — buttons, Esc, overlay — resolves the
    // promise exactly once. Leaving it on `onOpenChange={setOpen}` (the old
    // code) meant an Esc/overlay dismissal never resolved, hanging the caller.
    const resolveRef = useRef<((value: boolean) => void) | null>(null)
    const resultRef = useRef(false)

    const settle = useCallback(() => {
        const resolve = resolveRef.current
        if (!resolve) return
        resolveRef.current = null
        resolve(resultRef.current)
    }, [])

    const confirm = useCallback((opts: ConfirmOptions) => {
        setOptions(opts)
        resultRef.current = false
        setOpen(true)
        return new Promise<boolean>((resolve) => {
            resolveRef.current = resolve
        })
    }, [])

    const handleCancel = () => {
        resultRef.current = false
        setOpen(false)
        settle()
    }

    const handleConfirm = () => {
        resultRef.current = true
        setOpen(false)
        settle()
    }

    // Esc / overlay / any Radix-driven close: treat as "cancel" and resolve.
    const handleOpenChange = (next: boolean) => {
        setOpen(next)
        if (!next) settle()
    }

    const isDestructive = options.variant === "destructive"

    // One shared dialog chrome for every confirm in the app — only the accent
    // (icon / title colour / confirm-button colour) and the default labels change
    // per variant. Changing this single component restyles all confirm() callers.
    //  • destructive → red trash icon + red title + red confirm ("暂不 / 确认删除")
    //  • default     → amber warning icon + neutral title + primary confirm ("取消 / 确认")
    const titleColor = isDestructive ? "text-[#f53f3f]" : "text-[#1d2129]"
    const confirmColor = isDestructive
        ? "bg-[#f53f3f] hover:bg-[#f53f3f]/90"
        : "btn-brand-primary bg-primary hover:bg-primary/90"
    const accentIcon = options.icon ?? (isDestructive
        ? <Trash2 className="size-5 shrink-0 text-[#f53f3f]" />
        : <AlertCircle className="size-5 shrink-0 text-[#ff7d00]" />)
    const defaultTitle = isDestructive
        ? localize("com_knowledge.confirm_delete_title")
        : localize("com_knowledge.prompt")
    const defaultCancel = isDestructive
        ? localize("com_knowledge.defer")
        : localize("com_knowledge.cancel")
    const defaultConfirm = isDestructive
        ? localize("com_knowledge.confirm_delete_action")
        : localize("com_knowledge.confirm")

    return (
        <ConfirmContext.Provider value={{ confirm }}>
            {children}
            <AlertDialog open={open} onOpenChange={handleOpenChange}>
                {/* Screen-centered card (not a mobile bottom-sheet). Mobile: full-width
                    equal buttons. PC: left-aligned title + right-aligned hug buttons. */}
                <AlertDialogContent
                    onOpenAutoFocus={(e) => e.preventDefault()}
                    className="inset-0 m-auto flex h-fit max-h-[calc(100dvh-2rem)] max-w-[calc(100%-2rem)] flex-col items-center gap-4 rounded-[20px] border border-[#ebebeb] p-6 shadow-[0_0_16px_0_rgba(3,7,117,0.05)] sm:max-w-[400px] sm:rounded-[20px]"
                >
                    <AlertDialogHeader className="w-full flex-row items-center justify-center gap-2 space-y-0 text-center sm:justify-start sm:text-left">
                        {accentIcon}
                        <AlertDialogTitle className={`text-base font-medium leading-6 ${titleColor}`}>
                            {options.title || defaultTitle}
                        </AlertDialogTitle>
                    </AlertDialogHeader>

                    <AlertDialogDescription className="w-full text-left text-sm leading-[22px] text-[#212121] whitespace-pre-line">
                        {options.description}
                    </AlertDialogDescription>

                    <AlertDialogFooter className="w-full flex-row gap-2 sm:space-x-0">
                        <AlertDialogCancel
                            onClick={handleCancel}
                            className="mt-0 h-auto flex-1 rounded-[6px] border-[#ebecf0] bg-white/50 px-4 py-[5px] text-sm font-normal text-[#070038] backdrop-blur-[4px] hover:bg-white/70 sm:mt-0 sm:flex-none"
                        >
                            {options.cancelText || defaultCancel}
                        </AlertDialogCancel>
                        <AlertDialogAction
                            onClick={handleConfirm}
                            className={`h-auto flex-1 rounded-[6px] px-4 py-[5px] text-sm font-normal text-white sm:flex-none ${confirmColor}`}
                        >
                            {options.confirmText || defaultConfirm}
                        </AlertDialogAction>
                    </AlertDialogFooter>
                </AlertDialogContent>
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