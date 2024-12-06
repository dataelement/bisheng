import KnowledgeSelect from "@/components/bs-comp/selectComponent/knowledge";
import { TextAreaComponentType } from "@/types/components";
import { useMemo } from "react";

export default function CollectionNameComponent({
    id,
    value,
    onChange,
    onSelect,
    disabled,
}: TextAreaComponentType & { onSelect: (name: string, collectionId: any) => void }) {

    const handleChange = ([obj]) => {
        onSelect(obj.label, obj.value);
    }

    const values = useMemo(() => [{ label: value, value: id }], [id, value])

    return <KnowledgeSelect
        disabled={disabled}
        value={values}
        onChange={handleChange}
    />
    //     <div className={disabled ? "pointer-events-none w-full " : " w-full"}>
    //         <div className="flex w-full items-center" onClick={() => {
    //             openPopUp(
    //                 <dialog className={`modal bg-blur-shared modal-open`}>
    //                     <form method="dialog" className="max-w-[400px] flex flex-col modal-box bg-[#fff] shadow-lg dark:bg-background" onClick={e => e.stopPropagation()}>
    //                         <button className="btn btn-sm btn-circle btn-ghost absolute right-2 top-2" onClick={closePopUp}>✕</button>
    //                         <SelectCollection collectionId={id} onChange={handleChange}></SelectCollection>
    //                     </form>
    //                 </dialog>
    //             )
    //         }}>
    //             <span className={(disabled ? " input-disable input-ring " : "") + " input-primary text-muted-foreground "} >
    //                 {myValue !== "" ? myValue : "Please enter..."}
    //             </span>
    //             <button>
    //                 <HardDrive strokeWidth={1.5} className={"icons-parameters-comp" + (disabled ? " text-ring" : " hover:text-accent-foreground")} />
    //             </button>
    //         </div>
    //     </div>
    // );
}
