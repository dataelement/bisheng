import { useContext, useEffect, useState } from "react";
import { PopUpContext } from "../../contexts/popUpContext";
import { FloatComponentType } from "../../types/components";

export default function IntComponent({
  value,
  onChange,
  disabled,
  editNode = false,
}: FloatComponentType) {
  const [myValue, setMyValue] = useState(value ?? "");
  const min = 0;
  const { closePopUp } = useContext(PopUpContext);

  useEffect(() => {
    if (disabled) {
      setMyValue("");
      onChange("");
    }
  }, [disabled, onChange]);

  useEffect(() => {
    setMyValue(value);
  }, [closePopUp]);

  return (
    <div
      className={
        "w-full " +
        (disabled ? "pointer-events-none w-full cursor-not-allowed" : "")
      }
    >
      <input
        onKeyDown={(event) => {
          if (
            event.key !== "Backspace" &&
            event.key !== "Enter" &&
            event.key !== "Delete" &&
            event.key !== "ArrowLeft" &&
            event.key !== "ArrowRight" &&
            event.key !== "Control" &&
            event.key !== "Meta" &&
            event.key !== "Shift" &&
            event.key !== "c" &&
            event.key !== "v" &&
            event.key !== "a" &&
            !/^[-]?\d*$/.test(event.key)
          ) {
            event.preventDefault();
          }
        }}
        type="number"
        step="1"
        min={min}
        onInput={(e: React.ChangeEvent<HTMLInputElement>) => {
          if (e.target.value < min.toString()) {
            e.target.value = min.toString();
          }
        }}
        value={myValue}
        className={
          editNode
            ? " input-edit-node "
            : " input-primary " + (disabled ? " input-disable" : "")
        }
        placeholder={editNode ? "integer" : "Enter an integer"}
        onChange={(e) => {
          setMyValue(e.target.value);
          onChange(e.target.value);
        }}
      />
    </div>
  );
}
