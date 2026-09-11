"use client"

import React, { createContext, useCallback, useContext, useRef, useState } from "react"

import { Outlined } from "bisheng-icons"
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
    /** Body content. Accepts rich nodes (e.g. a bolded target name), not just text. */
    description?: React.ReactNode
    cancelText?: string
    confirmText?: string
    variant?: "default" | "destructive"
    /** Override the title icon in the destructive variant (defaults to Trash2). */
    icon?: React.ReactNode
    /**
     * Acknowledge-only mode: hide the cancel button and keep just the confirm
     * action. For dead-end notices (an error the user can only take note of),
     * where a second "cancel" button would do exactly the same thing.
     */
    hideCancel?: boolean
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
    // Unprefixed colors are enough: AlertDialog's own defaults carry no dark:
    // color classes, so nothing outranks these in dark mode (see AlertDialog.tsx).
    const titleColor = isDestructive ? "text-danger" : "text-text-1"
    const confirmColor = isDestructive
        ? "bg-danger hover:bg-danger-hover"
        // bg-blue-500 = brand token (NOT shadcn's bg-primary, whose hsl var
        // flips to near-white in dark mode) — same classes as <Button> primary solid.
        : "btn-brand-primary bg-blue-500 hover:bg-blue-400"
    const accentIcon = options.icon ?? (isDestructive
        ? <Outlined.Delete className="size-5 shrink-0 text-danger" />
        : <Outlined.Attention className="size-5 shrink-0 text-warning" />)
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
                    className="inset-0 m-auto flex h-fit max-h-[calc(100dvh-2rem)] max-w-[calc(100%-2rem)] flex-col items-center gap-4 rounded-2xl border border-border-base p-5 shadow-[0_0_16px_0_rgba(3,7,117,0.05)] sm:max-w-[400px] sm:rounded-2xl"
                >
                    <AlertDialogHeader className="w-full flex-row items-center justify-center gap-2 space-y-0 text-center sm:justify-start sm:text-left">
                        {accentIcon}
                        <AlertDialogTitle className={`text-base font-medium leading-6 ${titleColor}`}>
                            {options.title || defaultTitle}
                        </AlertDialogTitle>
                    </AlertDialogHeader>

                    <AlertDialogDescription className="w-full text-left text-sm leading-[22px] text-text-1 whitespace-pre-line">
                        {options.description}
                    </AlertDialogDescription>

                    <AlertDialogFooter className="w-full flex-row gap-2 sm:space-x-0">
                        {!options.hideCancel && <AlertDialogCancel
                            onClick={handleCancel}
                            className="mt-0 h-8 flex-1 rounded-md border-border-base bg-transparent px-4 text-sm font-normal text-text-1 hover:bg-fill-1 focus:ring-0 focus:ring-offset-0 focus-visible:ring-2 focus-visible:ring-gray-400 focus-visible:ring-offset-2 sm:mt-0 sm:flex-none"
                        >
                            {options.cancelText || defaultCancel}
                        </AlertDialogCancel>}
                        <AlertDialogAction
                            onClick={handleConfirm}
                            className={`h-8 flex-1 rounded-md px-4 text-sm font-normal text-white focus:ring-0 focus:ring-offset-0 focus-visible:ring-2 focus-visible:ring-gray-400 focus-visible:ring-offset-2 sm:flex-none ${confirmColor}`}
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