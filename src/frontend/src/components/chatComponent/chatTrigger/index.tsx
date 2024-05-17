import { MessagesSquare } from "lucide-react";

import { useContext } from "react";
import {
  CHAT_CANNOT_OPEN_DESCRIPTION,
  CHAT_CANNOT_OPEN_TITLE,
  FLOW_NOT_BUILT_DESCRIPTION,
  FLOW_NOT_BUILT_TITLE,
} from "../../../constants";
import { alertContext } from "../../../contexts/alertContext";

export default function ChatTrigger({ open, setOpen, isBuilt, canOpen }) {
  const { setErrorData } = useContext(alertContext);

  function handleClick() {
    if (isBuilt) {
      if (canOpen) {
        setOpen(true);
      } else {
        setErrorData({
          title: CHAT_CANNOT_OPEN_TITLE,
          list: [CHAT_CANNOT_OPEN_DESCRIPTION],
        });
      }
    } else {
      setErrorData({
        title: FLOW_NOT_BUILT_TITLE,
        list: [FLOW_NOT_BUILT_DESCRIPTION],
      });
    }
  }

  return (
    <button
      onClick={handleClick}
      className={
        "shadow-round-btn-shadow hover:shadow-round-btn-shadow message-button " +
        (!isBuilt || !canOpen ? "cursor-not-allowed" : "cursor-pointer")
      }
    >
      <div className="flex gap-3">
        <MessagesSquare
          className={
            "h-6 w-6 transition-all " +
            (isBuilt && canOpen
              ? "message-button-icon"
              : "disabled-message-button-icon")
          }
          style={{ color: "white" }}
          strokeWidth={1.5}
        />
      </div>
    </button>
  );
}
