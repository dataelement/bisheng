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
    onClose?: () => void
    onCancel?: () => void
    onOk?: (next) => void
}

let openFn = (_: ConfirmParams) => { }

function ConfirmWrapper() {

    const [open, setOpen] = useState(false)
    const paramRef = useRef(null)

    openFn = (params: ConfirmParams) => {
        paramRef.current = params
        setOpen(true)
    }

    const close = () => {
        paramRef.current?.onClose?.()
        setOpen(false)
    }

    const handleCancelClick = () => {
        paramRef.current?.onCancel?.()
        close()
    }

    const handleOkClick = () => {
        paramRef.current?.onOk
            ? paramRef.current?.onOk?.(close)
            : close()
    }

    if (!paramRef.current) return null
    const { title, desc, okTxt, canelTxt, showClose = true } = paramRef.current

    return (
        <AlertDialog open={open} onOpenChange={setOpen}>
            <AlertDialogContent>
                <AlertDialogHeader className="relative">
                    <div><TipIcon /></div>
                    {showClose && <X onClick={close} className="absolute right-0 top-[-0.5rem] cursor-pointer text-gray-400 hover:text-gray-600"></X>}
                    <AlertDialogTitle>{title}</AlertDialogTitle>
                    <AlertDialogDescription className="text-popover-foreground">
                        {desc}
                    </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                    <AlertDialogCancel onClick={handleCancelClick} className="px-11">{canelTxt}</AlertDialogCancel>
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
