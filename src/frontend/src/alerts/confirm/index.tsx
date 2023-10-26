import { useRef, useState } from "react";
import ReactDOM from "react-dom";
import { Button } from "../../components/ui/button";
import { useTranslation } from "react-i18next";

interface ConfirmParams {
  title?: string
  desc: string
  canelTxt?: string
  okTxt?: string
  onClose?: () => void
  onOk?: (next) => void
}

let openFn = (_: ConfirmParams) => { }
function ConfirmWrapper() {
  const { t } = useTranslation()

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

  const handleOkClick = () => {
    paramRef.current?.onOk
      ? paramRef.current?.onOk?.(close)
      : close()
  }

  if (!paramRef.current) return null
  const { title, desc, okTxt, canelTxt } = paramRef.current

  return <dialog className={`modal ${open && 'modal-open'}`}>
    <form method="dialog" className="modal-box w-[360px] bg-[#fff] shadow-lg dark:bg-background">
      <h3 className="font-bold text-lg">{title || t('prompt')}</h3>
      <p className="py-4">{desc}</p>
      <div className="modal-action">
        <Button className="h-8 rounded-full" variant="outline" onClick={close}>{canelTxt || t('cancel')}</Button>
        <Button className="h-8 rounded-full" variant="destructive" onClick={handleOkClick}>{okTxt || t('confirmButton')}</Button>
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
  openFn(params)
}
