
import { TipIcon } from "@/components/bs-icons/tip"
import i18next from "i18next"
import { X } from "lucide-react"
import { useRef, useState } from "react"
import ReactDOM from "react-dom"
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

(function () {
    // 挂载组件
    let el = document.getElementById('#confirm-wrap');
    if (!el) {
        el = document.createElement('div')
        el.id = 'confirm-wrap'
        document.body.append(el)
    }
    ReactDOM.render(<ConfirmWrapper />, el);
})();


const bsConfirm = (params: ConfirmParams) => {
    const resource = i18next.getResourceBundle(i18next.language, 'bs')

    openFn({
        title: resource.prompt,
        canelTxt: resource.cancel,
        okTxt: resource.confirmButton,
        ...params,
    })
}
export { bsConfirm }
