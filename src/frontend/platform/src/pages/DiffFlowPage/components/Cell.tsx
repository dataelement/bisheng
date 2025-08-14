import Skeleton from "@/components/bs-ui/skeleton";
import MessageMarkDown from "@/pages/BuildPage/flow/FlowChat/MessageMarkDown";
import { useDiffFlowStore } from "@/store/diffFlowStore";
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";

const Cell = forwardRef((props, ref) => {

    const [value, setValue] = useState('')
    const [loading, setLoading] = useState(false)

    useImperativeHandle(ref, () => ({
        loading: () => {
            setLoading(true)
        },
        loaded: () => {
            setLoading(false)
        },
        setData: (val) => {
            setLoading(false)

            let i = 0
            const print = () => {
                const value = val.substring(0, i++)
                setValue(value)
                i < val.length && setTimeout(print, Math.floor(Math.random() * 10) + 20)
            }
            print()
        },
        getData() {
            return value
        }
    }));

    if (loading) return <Skeleton className="h-4 w-[200px]" />

    return <div>
        <MessageMarkDown message={value.toString()} />
    </div>
})


export default function CellWarp({ qIndex, versionId }) {
    const ref = useRef(null);
    const addCellRef = useDiffFlowStore(state => state.addCellRef);
    const removeCellRef = useDiffFlowStore(state => state.removeCellRef);

    useEffect(() => {
        const key = `${qIndex}-${versionId}`
        addCellRef(key, ref);

        // 组件卸载时删除 ref
        return () => {
            removeCellRef(key);
        };
    }, [qIndex, versionId, addCellRef, removeCellRef]);

    return <Cell ref={ref} />
};
