import { HardDrive } from "lucide-react";
import { useContext, useEffect, useState } from "react";
import { PopUpContext } from "../../../../contexts/popUpContext";
import { TextAreaComponentType } from "../../../../types/components";
import SelectCollection from "./selectCollection";

export default function CollectionNameComponent({
    id,
    value,
    onChange,
    onSelect,
    disabled,
}: TextAreaComponentType & { onSelect: (name: string, collectionId: any) => void }) {
    const [myValue, setMyValue] = useState(value);
    // const [collectionId, setCollectionId] = useState<number | ''>("")
    useEffect(() => {
        setMyValue(value);
        // setCollectionId(id)
    }, [value]);

    const { openPopUp, closePopUp } = useContext(PopUpContext);
    useEffect(() => {
        if (disabled) {
            setMyValue("");
            onSelect("", "");
        }
    }, [disabled, onSelect]);

    const handleChange = (obj) => {
        setMyValue(obj.name);
        onSelect(obj.name, obj.id);
        closePopUp();
    }

    return (
        <div className={disabled ? "pointer-events-none w-full " : " w-full"}>
            <div className="flex w-full items-center" onClick={() => {
                openPopUp(
                    <dialog className={`modal bg-blur-shared modal-open`}>
                        <form method="dialog" className="max-w-[400px] flex flex-col modal-box bg-[#fff] shadow-lg dark:bg-background" onClick={e => e.stopPropagation()}>
                            <button className="btn btn-sm btn-circle btn-ghost absolute right-2 top-2" onClick={closePopUp}>✕</button>
                            <SelectCollection collectionId={id} onChange={handleChange}></SelectCollection>
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
