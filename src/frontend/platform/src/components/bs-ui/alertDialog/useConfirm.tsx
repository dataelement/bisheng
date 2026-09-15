// @ts-strict-ignore

import { TipIcon } from "@/components/bs-icons/tip"
import i18next from "i18next"
import { X } from "lucide-react"
import { useRef, useState } from "react"
import { createRoot } from "react-dom/client"
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "."

interface ConfirmParams {
    title?: string
    desc: string | React.ReactNode
    canelTxt?: string
    okTxt?: string
    showClose?: boolean
    /** Acknowledge-only: hide Cancel so the user has a single way out. */
    hideCancel?: boolean
    onClose?: () => void
    onCancel?: () => void
    onOk?: (next) => void
}

let openFn = (_: ConfirmParams) => { }

function ConfirmWrapper() {

    const [open, setOpen] = useState(false)
    const paramRef = useRef(null)
    const settledRef = useRef(false)

    openFn = (params: ConfirmParams) => {
        paramRef.current = params
        settledRef.current = false
        setOpen(true)
    }

    const close = () => {
        paramRef.current?.onClose?.()
        setOpen(false)
    }

    const handleOkClick = () => {
        if (settledRef.current) return
        settledRef.current = true
        paramRef.current?.onOk
            ? paramRef.current?.onOk?.(close)
            : close()
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
    const { title, desc, okTxt, canelTxt, showClose = true, hideCancel = false } = paramRef.current

    return (
        <AlertDialog
            open={open}
            onOpenChange={(next) => {
                if (!next && paramRef.current?.hideCancel) {
                    handleOkClick()
                    return
                }
                setOpen(next)
            }}
        >
            <AlertDialogContent>
                <AlertDialogHeader className="relative">
                    <div><TipIcon /></div>
                    {showClose && <X onClick={hideCancel ? handleOkClick : close} className="absolute right-0 top-[-0.5rem] cursor-pointer text-gray-400 hover:text-gray-600"></X>}
                    <AlertDialogTitle>{title}</AlertDialogTitle>
                    <AlertDialogDescription className="whitespace-pre-line text-popover-foreground">
                        {desc}
                    </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                    {!hideCancel && <AlertDialogCancel onClick={handleCancelClick} className="px-11">{canelTxt}</AlertDialogCancel>}
                    <AlertDialogAction onClick={handleOkClick} className="px-11">{okTxt}</AlertDialogAction>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    )
}

let confirmRoot: ReturnType<typeof createRoot> | null = null;

(function () {
    // 挂载组件
    let el = document.getElementById('confirm-wrap');
    if (!el) {
        el = document.createElement('div');
        el.id = 'confirm-wrap';
        document.body.append(el);
    }
    // 统一使用 createRoot (React 18+)
    if (!confirmRoot) {
        confirmRoot = createRoot(el);
    }
    confirmRoot.render(<ConfirmWrapper />);
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
