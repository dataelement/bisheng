
import { LoadIcon } from "@/components/bs-icons"
import { TipIcon } from "@/components/bs-icons/tip"
import i18next from "i18next"
import { X } from "lucide-react"
import { useRef, useState, type KeyboardEvent, type MouseEvent } from "react"
import { createRoot } from "react-dom/client"
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "."

interface ConfirmParams {
    title?: string
    desc: string | React.ReactNode
    canelTxt?: string
    okTxt?: string
    okLoadingTxt?: string
    showClose?: boolean
    onClose?: () => void
    onCancel?: () => void
    onOk?: (next: () => void) => void | Promise<void>
    okDisabled?: boolean
    okHidden?: boolean
}

let openFn = (_: ConfirmParams) => { }

function ConfirmWrapper() {

    const [open, setOpen] = useState(false)
    const [okLoading, setOkLoading] = useState(false)
    const paramRef = useRef<ConfirmParams | null>(null)

    openFn = (params: ConfirmParams) => {
        paramRef.current = params
        setOkLoading(false)
        setOpen(true)
    }

    const close = () => {
        paramRef.current?.onClose?.()
        setOkLoading(false)
        setOpen(false)
    }

    const handleCancelClick = () => {
        if (okLoading) return
        paramRef.current?.onCancel?.()
        close()
    }

    const runOk = async () => {
        if (okLoading || paramRef.current?.okDisabled) return
        const onOk = paramRef.current?.onOk
        if (!onOk) {
            close()
            return
        }
        setOkLoading(true)
        try {
            await Promise.resolve(onOk(close))
        } finally {
            setOkLoading(false)
        }
    }

    const handleOkClick = async (event: MouseEvent<HTMLButtonElement>) => {
        event.preventDefault()
        await runOk()
    }

    const handleContentKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
        if (okLoading) return
        if (event.key !== "Enter" || event.nativeEvent.isComposing) {
            return
        }
        event.preventDefault()
        void runOk()
    }

    const handleOpenChange = (nextOpen: boolean) => {
        if (!nextOpen && okLoading) return
        setOpen(nextOpen)
        if (!nextOpen) {
            paramRef.current?.onClose?.()
            setOkLoading(false)
        }
    }

    if (!paramRef.current) return null
    const {
        title,
        desc,
        okTxt,
        okLoadingTxt,
        canelTxt,
        showClose = true,
        okDisabled = false,
        okHidden = false,
    } = paramRef.current

    return (
        <AlertDialog open={open} onOpenChange={handleOpenChange}>
            <AlertDialogContent onKeyDown={handleContentKeyDown}>
                <AlertDialogHeader className="relative">
                    <div><TipIcon /></div>
                    {showClose && !okLoading && (
                        <X
                            onClick={close}
                            className="absolute right-0 top-[-0.5rem] cursor-pointer text-gray-400 hover:text-gray-600"
                        />
                    )}
                    <AlertDialogTitle>{title}</AlertDialogTitle>
                    <AlertDialogDescription className="text-popover-foreground">
                        {desc}
                    </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                    <AlertDialogCancel
                        onClick={handleCancelClick}
                        disabled={okLoading}
                        className="px-11"
                    >
                        {canelTxt}
                    </AlertDialogCancel>
                    {!okHidden && (
                        <AlertDialogAction
                            onClick={(event) => void handleOkClick(event)}
                            disabled={okDisabled || okLoading}
                            className="px-11"
                        >
                            {okLoading && <LoadIcon className="mr-1" />}
                            {okLoading ? okLoadingTxt || okTxt : okTxt}
                        </AlertDialogAction>
                    )}
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
    const resource = i18next.getResourceBundle(i18next.language, 'bs')

    openFn({
        title: resource.prompt,
        canelTxt: resource.cancel,
        okTxt: resource.confirmButton,
        ...params,
    })
}
export { bsConfirm }
