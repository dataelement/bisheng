import { Input } from "@/components/bs-ui/input";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select";
import { QuestionTooltip } from "@/components/bs-ui/tooltip";
import { useEffect, useState } from "react";

export const InputField = ({ label, type = "text", id, name, required = false, placeholder = '', value, onChange, error = '', tooltip = '' }) => {

    return <div key={id} className="">
        <label htmlFor={id} className="bisheng-label flex items-center gap-1">
            {label}
            {tooltip && <QuestionTooltip content={tooltip} />}
            {required && <span className="bisheng-tip">*</span>}
        </label>
        <Input
            type={type}
            id={id}
            name={name}
            placeholder={placeholder}
            className="mt-2"
            value={value}
            autoComplete="off"
            onChange={onChange}
        />
        {error && <p className="bisheng-tip mt-1">{label} 不能为空</p>}
    </div>
};


export const SelectField = ({ label, id, name, required = false, value, onChange, options = [], error = '', tooltip = '' }) => (
    <div key={id} className="">
        <label htmlFor={id} className="bisheng-label flex items-center gap-1">
            {label}
            {tooltip && <QuestionTooltip content={tooltip} />}
            {required && <span className="bisheng-tip">*</span>}
        </label>
        <Select value={value} onValueChange={onChange}>
            <SelectTrigger className="h-8 mt-2">
                <SelectValue placeholder="请选择" />
            </SelectTrigger>
            <SelectContent>
                <SelectGroup>
                    {options.map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                            {option.label}
                        </SelectItem>
                    ))}
                </SelectGroup>
            </SelectContent>
        </Select>
        {error && <p className="bisheng-tip mt-1">{label} 不能为空</p>}
    </div>
);
