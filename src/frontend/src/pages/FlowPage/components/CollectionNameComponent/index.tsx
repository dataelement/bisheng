import { HardDrive } from "lucide-react";
import { useContext, useEffect, useState } from "react";
import { PopUpContext } from "../../../../contexts/popUpContext";
import { TextAreaComponentType } from "../../../../types/components";
import SelectCollection from "./selectCollection";

export default function CollectionNameComponent({
    value,
    onChange,
    disabled,
}: TextAreaComponentType) {
    const [myValue, setMyValue] = useState(value);
    useEffect(() => {
        setMyValue(value);
    }, [value]);

    const { openPopUp, closePopUp } = useContext(PopUpContext);
    useEffect(() => {
        if (disabled) {
            setMyValue("");
            onChange("");
        }
    }, [disabled, onChange]);

    const handleChange = (id: string) => {
        setMyValue(id);
        onChange(id);
        closePopUp();
    }

    return (
        <div className={disabled ? "pointer-events-none w-full " : " w-full"}>
            <div className="flex w-full items-center" onClick={() => {
                openPopUp(
                    <dialog className={`modal bg-blur-shared modal-open`}>
                        <form method="dialog" className="max-w-[400px] flex flex-col modal-box bg-[#fff] shadow-lg dark:bg-background" onClick={e => e.stopPropagation()}>
                            <button className="btn btn-sm btn-circle btn-ghost absolute right-2 top-2" onClick={closePopUp}>✕</button>
                            <SelectCollection collectionId={myValue} onChange={handleChange}></SelectCollection>
                        </form>
                    </dialog>
                )
            }}>
                <span className={(disabled ? " input-disable input-ring " : "") + " input-primary text-muted-foreground "} >
                    {myValue !== "" ? myValue : "Please enter..."}
                </span>
                <button>
                    <HardDrive strokeWidth={1.5} className={"icons-parameters-comp" + (disabled ? " text-ring" : " hover:text-accent-foreground")} />
                </button>
            </div>
        </div>
    );
}
