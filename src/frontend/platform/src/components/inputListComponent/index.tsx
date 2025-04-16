import { useContext, useEffect, useRef, useState } from "react";
import { InputListComponentType } from "../../types/components";

import cloneDeep from "lodash-es/cloneDeep";
import { Plus, X } from "lucide-react";
import { PopUpContext } from "../../contexts/popUpContext";

export default function InputListComponent({
  value,
  onChange,
  disabled,
  isGroup = false,
  editNode = false
}: InputListComponentType) {
  const [inputList, setInputList] = useState(value ?? [""]);
  const { closePopUp } = useContext(PopUpContext);

  useEffect(() => {
    if (disabled) {
      setInputList([""]);
      onChange([""]);
    }
  }, [disabled, onChange]);

  useEffect(() => {
    setInputList(value);
  }, [closePopUp]);

  // list超出滚动，配合template-scrollbar使用（TODO 抽象为插槽）
  const scrollBodyRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const scrollFun = (event) => {
      // 双指缩放 event.ctrlKey为 true
      if (!event.ctrlKey) {
        event.stopPropagation();
      }
    }
    scrollBodyRef.current.addEventListener('wheel', scrollFun);
    return () => scrollBodyRef.current?.removeEventListener('wheel', scrollFun);
  }, [])

  return (
    <div
      ref={scrollBodyRef}
      className={`${disabled ? "pointer-events-none cursor-not-allowed" : ""}
       flex flex-col gap-3 template-scrollbar 
       ${isGroup && "max-h-[170px]"}`
      }
    >
      {inputList.map((i, idx) => {
        return (
          <div key={idx} className="flex w-full gap-3">
            <input
              type="text"
              value={i}
              className={
                editNode
                  ? "input-edit-node "
                  : "input-primary " + (disabled ? "input-disable" : "")
              }
              placeholder="input..."
              onChange={(e) => {
                setInputList((old) => {
                  let newInputList = cloneDeep(old);
                  newInputList[idx] = e.target.value;
                  onChange(newInputList);
                  return newInputList;
                });
              }}
            />
            {idx === inputList.length - 1 && (
              <button
                onClick={() => {
                  setInputList((old) => {
                    let newInputList = cloneDeep(old);
                    newInputList.push("");
                    onChange(newInputList);
                    return newInputList;
                  });
                }}
              >
                <Plus className={"h-4 w-4 hover:text-accent-foreground"} />
              </button>
            )}
            {
              inputList.length !== 1 && <button
                onClick={() => {
                  setInputList((old) => {
                    let newInputList = cloneDeep(old);
                    newInputList.splice(idx, 1);
                    onChange(newInputList);
                    return newInputList;
                  });
                }}
              >
                <X className="h-4 w-4 hover:text-status-red" />
              </button>
            }
          </div>
        );
      })}
    </div>
  );
}