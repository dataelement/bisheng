import { useContext, useEffect, useState } from "react";
import { PopUpContext } from "../../contexts/popUpContext";
import { FloatComponentType } from "../../types/components";

export default function FloatComponent({
  value,
  onChange,
  disabled,
  editNode = false,
}: FloatComponentType) {
  const [myValue, setMyValue] = useState(value ?? "");
  const { closePopUp } = useContext(PopUpContext);

  const step = 0.1;
  const min = 0;
  const max = 1;

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
    <div className={"w-full " + (disabled ? "float-component-pointer" : "")}>
      <input
        type="number"
        step={step}
        min={min}
        onInput={(e: React.ChangeEvent<HTMLInputElement>) => {
          if (e.target.value < min.toString()) {
            e.target.value = min.toString();
          }
          if (e.target.value > max.toString()) {
            e.target.value = max.toString();
          }
        }}
        max={max}
        value={myValue}
        className={
          editNode
            ? "input-edit-node"
            : "input-primary" + (disabled ? " input-disable " : "")
        }
        placeholder={
          editNode ? "number from 0 to 1" : "Input a number from 0 to 1"
        }
        onChange={(e) => {
          setMyValue(e.target.value);
          onChange(e.target.value);
        }}
      />
    </div>
  );
}
