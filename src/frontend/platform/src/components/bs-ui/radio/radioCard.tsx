import React from "react";
import { cname } from "../utils";

export default function RadioCard({ calssName = '', checked, title, description = '' }) {

    return <div className={cname('w-96 border rounded-sm flex gap-2 p-4 cursor-pointer transition-all hover:border-primary/50', calssName, checked && 'border-primary bg-primary/10')}>
        <div className={`bg-[#fff] border border-gray-400 rounded-full w-5 h-5 min-w-5 ${checked && 'bg-primary flex justify-center items-center'}`}>
            {checked && <div className="w-2 h-2 bg-gray-50 rounded-full" />}
        </div>
        <div>
            <div className="text-sm font-medium leading-none mt-0.5 mb-2">{title}</div>
            <div className="text-sm text-muted-foreground">{description}</div>
        </div>
    </div>
};
