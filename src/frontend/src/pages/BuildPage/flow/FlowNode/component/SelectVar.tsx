import { Select, SelectContent, SelectTrigger } from "@/components/bs-ui/select"
import { ChevronRight, SprayCan } from "lucide-react"
import { useRef, useState } from "react"
import { Colors, Icons } from "../../Sidebar"

export default function SelectVar({ nodeId, children, onSelect }) {
    const [open, setOpen] = useState(false)
    const getNodeDataByTemp = (temp) => {
        const IconComp = Icons[temp.type] || SprayCan
        const color = Colors[temp.type] || 'text-gray-950'

        return {
            id: temp.id,
            type: temp.type,
            name: temp.name,
            icon: <IconComp className={`size-5 ${color}`} />,
            desc: temp.description,
            data: temp.group_params
        }
    }
    const nodeTemps = []
    //  tempData.reduce((list, temp) => {
    //     const newNode = getNodeDataByTemp(temp)
    //     list.push(newNode)
    //     return list
    // }, [])

    // vars
    const [vars, setVars] = useState([])
    const currentMenuRef = useRef(null)
    const handleShowVars = (item) => {
        currentMenuRef.current = item
        console.log('1 :>> ', 1);
        // start节点 preset_question#0(中文)
        // input节点 key
        // agent xxx#0
        const _vars = []
        item.data.forEach(group => {
            group.params.forEach(param => {
                // TODO index dict
                if (param.global === 'key'
                    || (param.global === 'self' && nodeId === item.id)) {
                    _vars.push({
                        label: param.key,
                        value: param.key
                    })
                }
            });
        });

        setVars(_vars)
    }

    return <Select open={open} onOpenChange={setOpen}>
        <SelectTrigger showIcon={false} className={'group p-0 h-auto data-[placeholder]:text-inherit border-none bg-transparent shadow-none outline-none focus:shadow-none focus:outline-none focus:ring-0'}>
            {children}
        </SelectTrigger>
        <SelectContent>
            <div className="flex ">
                <div className="w-36 border-l first:border-none">
                    {nodeTemps.map(item =>
                        <div
                            className="relative flex justify-between w-full select-none items-center rounded-sm p-1.5 text-sm outline-none cursor-pointer hover:bg-[#EBF0FF] data-[focus=true]:bg-[#EBF0FF] dark:hover:bg-gray-700 dark:data-[focus=true]:bg-gray-700 data-[disabled]:pointer-events-none data-[disabled]:opacity-50"
                            onMouseEnter={() => handleShowVars(item)}
                        >
                            {item.icon}
                            <span className="w-28 overflow-hidden text-ellipsis ml-2">{item.name}</span>
                            <ChevronRight className="size-4" />
                        </div>
                    )}
                </div>
                {!!vars.length && <div className="w-36 border-l first:border-none">
                    {vars.map(v =>
                        <div
                            className="relative flex justify-between w-full select-none items-center rounded-sm p-1.5 text-sm outline-none cursor-pointer hover:bg-[#EBF0FF] data-[focus=true]:bg-[#EBF0FF] dark:hover:bg-gray-700 dark:data-[focus=true]:bg-gray-700 data-[disabled]:pointer-events-none data-[disabled]:opacity-50"
                            onClick={() => {
                                onSelect(currentMenuRef.current, v)
                                setOpen(false)
                            }}>
                            <span className="w-28 overflow-hidden text-ellipsis">{v.label}</span>
                            {/* {!isLeaf && (loading ? <LoadIcon className="text-foreground" /> : <ChevronRight className="size-4" />)} */}
                        </div>
                    )}
                </div>}
            </div>
        </SelectContent>
    </Select>
};
