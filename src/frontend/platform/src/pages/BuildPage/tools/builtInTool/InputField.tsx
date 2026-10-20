// @ts-strict-ignore
import { Input } from '@bisheng/ui';

import {
Select,
SelectContent,
SelectGroup,
SelectItem,
SelectTrigger,
SelectValue
} from "@/components/bs-ui/select";
import { useTranslation } from "react-i18next";
import { AppHint } from "../../components/AppHint";

export const InputField = ({
    label,
    type = "text",
    id,
    name,
    required = false,
    placeholder = '',
    value,
    onChange,
    error = '',
    tooltip = '',
    ...prop
}) => {
    const { t } = useTranslation('tool');

    return (
        <div key={id}>
            <label htmlFor={id} className="bisheng-label flex items-center gap-1">
                {label}
                {tooltip && <AppHint content={tooltip} />}
                {required && <span className="bisheng-tip">*</span>}
            </label>

            <Input type={type} id={id} name={name} placeholder={placeholder} value={value} autoComplete="off" onChange={onChange} min="0" {...prop} className={"mt-2"} />
            {error && (
                <p className="bisheng-tip mt-1">
                    {typeof error === "string"
                        ? error
                        : t("fieldCannotBeEmpty", { label })}
                </p>
            )}
        </div>
    );
};


export const SelectField = ({
    label,
    id,
    name,
    required = false,
    value,
    onChange,
    options = [],
    error = '',
    tooltip = ''
}) => {
    const { t } = useTranslation('tool');

    return (
        <div key={id}>
            <label htmlFor={id} className="bisheng-label flex items-center gap-1">
                {label}
                {tooltip && <AppHint content={tooltip} />}
                {required && <span className="bisheng-tip">*</span>}
            </label>

            <Select value={value} onValueChange={onChange}>
                <SelectTrigger className="h-8 mt-2">
                    <SelectValue placeholder={t("pleaseSelect")} />
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

            {error && (
                <p className="bisheng-tip mt-1">
                    {t("fieldCannotBeEmpty", { label })}
                </p>
            )}
        </div>
    );
};
