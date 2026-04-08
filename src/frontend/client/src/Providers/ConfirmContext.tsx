"use client"

import React, { createContext, useCallback, useContext, useState } from "react"

import { AlertCircle, X } from "lucide-react"
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

    return (
        <ConfirmContext.Provider value={{ confirm }}>
            {children}
            <AlertDialog open={open} onOpenChange={setOpen}>
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