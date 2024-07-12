import { Button } from "@/components/bs-ui/button";
import { Label } from "@/components/bs-ui/label";
import { useState } from "react";
import { SketchPicker } from 'react-color';

export default function HSLitem({ label, name, value, onChange }) {
    const [show, setShow] = useState(false)

    return <div className="flex items-center justify-between">
        <Label className="font-black">{label}</Label>
        <div>
            <Button variant="outline" className="p-2 h-8 bg-gray-100" onClick={() => setShow(!show)}>
                <span className="block w-8 h-4 rounded" style={{ background: `hsl(${value.h}, ${value.s * 100}%, ${value.l * 100}%)` }}></span>
            </Button>
            {show && <div className="absolute z-10">
                <div className="fixed top-0 left-0 w-full h-full" onClick={() => setShow(false)}></div>
                <SketchPicker
                    value={value}
                    presetColors={['#D9E3F0', '#F47373', '#697689', '#37D67A', '#2CCCE4', '#555555', '#dce775', '#ff8a65', '#ba68c8']}
                    onChangeComplete={(e) => { onChange(name, e.hsl), setShow(false) }}
                />
            </div>}
        </div>
    </div>
};
