import { CheckCircle2 } from "lucide-react";
import { useEffect, useState } from "react";
import { SuccessAlertType } from "../../types/alerts";

export default function SuccessAlert({
  title,
  id,
  removeAlert,
}: SuccessAlertType) {
  const [show, setShow] = useState(true);
  useEffect(() => {
    if (show) {
      setTimeout(() => {
        setShow(false);
        setTimeout(() => {
          removeAlert(id);
        }, 500);
      }, 5000);
    }
  }, [id, removeAlert, show]);
  return (
    <div
      onClick={() => {
        setShow(false);
        removeAlert(id);
      }}
      className="success-alert"
    >
      <div className="flex">
        <div className="flex-shrink-0">
          <CheckCircle2 className="success-alert-icon" aria-hidden="true" />
        </div>
        <div className="ml-3">
          <p className="success-alert-message">{title}</p>
        </div>
      </div>
    </div>
  );
}
