import i18next from "i18next";
import { useRef, useState } from "react";
import ReactDOM from "react-dom";
import { Button } from "../../components/bs-ui/button";
import { X } from "lucide-react";

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
  const { title, desc, okTxt, canelTxt, showClose = false } = paramRef.current

  return <dialog className={`modal ${open && 'modal-open'}`}>
    <form method="dialog" className="modal-box w-[360px] bg-[#fff] shadow-lg dark:bg-background relative">
      {showClose && <X size={20} onClick={close} className="absolute right-4 cursor-pointer text-gray-400 hover:text-gray-600"></X>}
      <h3 className="font-bold text-lg">{title}</h3>
      <p className="py-4">{desc}</p>
      <div className="modal-action">
        <Button className="h-8" variant="outline" onClick={handleCancelClick}>{canelTxt}</Button>
        <Button className="h-8" variant="destructive" onClick={handleOkClick}>{okTxt}</Button>
      </div>
    </form>
  </dialog>
}

(function () {
  let el = document.getElementById('#message-wrap');
  if (!el) {
    el = document.createElement('div')
    el.className = 'message-wrap'
    el.id = 'message-wrap'
    document.body.append(el)
  }
  ReactDOM.render(<ConfirmWrapper />, el);
})();


export const bsconfirm = (params: ConfirmParams) => {
  const resource = i18next.getResourceBundle(i18next.language, 'bs')

  openFn({
    title: resource.prompt,
    canelTxt: resource.cancel,
    okTxt: resource.confirmButton,
    ...params,
  })
}
