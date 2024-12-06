import { TitleIconBg } from "@/components/bs-comp/cardComponent";
import ToolsSheet from "@/components/bs-comp/sheets/ToolsSheet";
import { ToolIcon } from "@/components/bs-icons";
import { Button } from "@/components/bs-ui/button";
import { CircleMinus } from "lucide-react";
import { useState } from "react";

export default function ToolItem({ data, onChange }) {
    // { key: string, label: string }[]
    const [value, setValue] = useState(() => data.value.map(el => ({ id: el.key, name: el.label })))

    return <div>
        <div>
            {value.map((tool) => (
                <div
                    key={tool.id}
                    className="group mt-2 flex cursor-pointer items-center justify-between"
                >
                    <div className="flex items-center gap-2">
                        <TitleIconBg id={tool.id} className="h-6 w-6">
                            <ToolIcon />
                        </TitleIconBg>
                        <p className="text-sm">{tool.name}</p>
                    </div>
                    <CircleMinus
                        className="w-4 h-4 hidden text-primary group-hover:block"
                        onClick={() => {
                            const newValue = value.filter((t) => t.id !== tool.id)
                            setValue(newValue)
                            onChange(newValue.map(el => ({ key: el.id, label: el.name })))
                        }}
                    />
                </div>
            ))}
        </div>
        <ToolsSheet select={value} onSelect={(val) => {
            const newValue = [...value, val]
            setValue(newValue)
            onChange(newValue.map(el => ({ key: el.id, label: el.name })))
        }}>
            <Button onClick={() => { }} variant='outline' className="border-primary text-primary mt-2">
                {data.label}
            </Button>
        </ToolsSheet>
    </div>
};
