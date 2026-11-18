import { Button } from "@bisheng/ui"
import * as AlertDialogPrimitive from "@radix-ui/react-alert-dialog"
import { Outlined } from "bisheng-icons"
import { showApiError } from "@/controllers/request"
import { PlatformLoadingProvider } from "@/components/bs-icons/loading/PlatformLoadingProvider"
import i18next from "i18next"
import { useCallback, useEffect, useRef, useState } from "react"
import { createRoot } from "react-dom/client"
import { AlertDialog, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "."

interface ConfirmParams {
    title?: string
    desc: string | React.ReactNode
    canelTxt?: string
    okTxt?: string
    variant?: "default" | "destructive"
    /** @deprecated Confirmations close through their explicit action buttons. */
    showClose?: boolean
    /** Acknowledge-only: hide Cancel so the user has a single way out. */
    hideCancel?: boolean
    /** Close only this confirmation when its owning view is invalidated. */
    signal?: AbortSignal
    onClose?: () => void
    onCancel?: () => void
    onOk?: (next: () => void) => unknown
}

let openFn = (_: ConfirmParams) => { }

function ConfirmWrapper() {

    const [open, setOpen] = useState(false)
    const [pending, setPending] = useState(false)
    const [revision, setRevision] = useState(0)
    const paramRef = useRef<ConfirmParams | null>(null)
    const contentRef = useRef<HTMLDivElement | null>(null)
    const openerRef = useRef<HTMLElement | null>(null)
    const settledRef = useRef(false)
    const closedRef = useRef(true)

    openFn = (params: ConfirmParams) => {
        const activeElement = document.activeElement
        if (activeElement instanceof HTMLElement && !contentRef.current?.contains(activeElement)) {
            openerRef.current = activeElement
        }
        paramRef.current = params
        closedRef.current = false
        settledRef.current = false
        setPending(false)
        setOpen(true)
        setRevision(value => value + 1)
    }

    const close = useCallback((params: ConfirmParams | null = paramRef.current) => {
        if (paramRef.current !== params || closedRef.current) return
        // Mark closed before callbacks, which may synchronously abort the owner signal.
        closedRef.current = true
        setOpen(false)
        params?.onClose?.()
    }, [])

    useEffect(() => {
        const params = paramRef.current
        const signal = params?.signal as AbortSignal | undefined
        if (!open || !signal) return
        const abort = () => close(params)
        signal.addEventListener("abort", abort, { once: true })
        if (signal.aborted) abort()
        return () => signal.removeEventListener("abort", abort)
    }, [open, revision, close])

    const handleOkClick = () => {
        if (settledRef.current || closedRef.current) return
        settledRef.current = true
        setPending(true)
        const params = paramRef.current
        void Promise.resolve().then(() => {
            if (closedRef.current || paramRef.current !== params) return
            return params?.onOk ? params.onOk(() => close(params)) : close(params)
        }).catch(showApiError).finally(() => {
            if (paramRef.current !== params) return
            settledRef.current = false
            setPending(false)
        })
    }

    const handleCancelClick = () => {
        if (paramRef.current?.hideCancel) {
            handleOkClick()
            return
        }
        paramRef.current?.onCancel?.()
        close()
    }

    if (!paramRef.current) return null
    const { title, desc, okTxt, canelTxt, hideCancel = false, variant = hideCancel ? "default" : "destructive" } = paramRef.current
    const isDestructive = variant === "destructive"

    return (
        <AlertDialog
            open={open}
            onOpenChange={(next) => {
                if (pending) return
                if (!next && paramRef.current?.hideCancel) {
                    handleOkClick()
                    return
                }
                if (!next) close()
            }}
        >
            <AlertDialogContent
                ref={contentRef}
                overlayClassName="z-[1000] bg-black/40 dark:bg-black/60"
                className="z-[1000] flex max-h-[calc(100dvh-2rem)] max-w-[calc(100%-2rem)] flex-col gap-4 rounded-2xl border-border-base bg-bg-page p-5 text-text-1 shadow-modal sm:max-w-[400px] sm:rounded-2xl"
                onCloseAutoFocus={(event) => {
                    if (openerRef.current?.isConnected) {
                        event.preventDefault()
                        openerRef.current.focus()
                    }
                }}
            >
                <AlertDialogHeader className="shrink-0 flex-row items-center gap-2 space-y-0 text-left">
                    {isDestructive
                        ? <Outlined.Delete aria-hidden className="size-5 shrink-0 text-danger" />
                        : <Outlined.Attention aria-hidden className="size-5 shrink-0 text-blue-500" />}
                    <AlertDialogTitle className={`text-left text-base font-medium leading-6 ${isDestructive ? "text-danger" : "text-text-1"}`}>
                        {title}
                    </AlertDialogTitle>
                </AlertDialogHeader>
                <AlertDialogDescription className="min-h-0 overflow-y-auto whitespace-pre-line text-left text-sm leading-[22px] text-text-1">
                    {desc}
                </AlertDialogDescription>
                <AlertDialogFooter className="shrink-0 flex-row justify-end gap-3 sm:space-x-0">
                    {!hideCancel && (
                        <AlertDialogPrimitive.Cancel asChild>
                            <Button type="button" variant="outlined" color="default" disabled={pending} onClick={handleCancelClick} className="min-w-[60px] flex-1 sm:flex-none">
                                {canelTxt}
                            </Button>
                        </AlertDialogPrimitive.Cancel>
                    )}
                    <AlertDialogPrimitive.Action asChild>
                        <Button type="button" color={isDestructive ? "danger" : "primary"} loading={pending} disabled={pending}
                            onClick={(event) => { event.preventDefault(); handleOkClick() }} className="min-w-[60px] flex-1 sm:flex-none">
                            {okTxt}
                        </Button>
                    </AlertDialogPrimitive.Action>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    )
}

let confirmRoot: ReturnType<typeof createRoot> | null = null;

(function () {
    // Mount the singleton dialog host.
    let el = document.getElementById('confirm-wrap');
    if (!el) {
        el = document.createElement('div');
        el.id = 'confirm-wrap';
        document.body.append(el);
    }
    // Reuse the React 18 root.
    if (!confirmRoot) {
        confirmRoot = createRoot(el);
    }
    confirmRoot.render(<PlatformLoadingProvider><ConfirmWrapper /></PlatformLoadingProvider>);
})();


const bsConfirm = (params: ConfirmParams) => {
    // t(), not getResourceBundle(): the bundle is undefined whenever the active
    // language has no loaded resources — a namespace still in flight, or a tag
    // with no bundle to load at all. Reading .prompt off it threw and killed
    // every confirm dialog, so deletes and cancels silently did nothing.
    openFn({
        title: i18next.t('prompt', { ns: 'bs', defaultValue: 'Confirmation' }),
        canelTxt: i18next.t('cancel', { ns: 'bs', defaultValue: 'Cancel' }),
        okTxt: i18next.t('confirmButton', { ns: 'bs', defaultValue: 'Confirm' }),
        ...params,
    })
}
export { bsConfirm }
