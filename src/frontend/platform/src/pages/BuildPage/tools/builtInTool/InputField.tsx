// @ts-strict-ignore
import { Input, Select } from '@bisheng/ui';

import { useSelectLabels } from "@/components/bs-comp/formFields/useSelectLabels";
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
    const selectLabels = useSelectLabels();

    return (
        <div key={id}>
            <label htmlFor={id} className="bisheng-label flex items-center gap-1">
                {label}
                {tooltip && <AppHint content={tooltip} />}
                {required && <span className="bisheng-tip">*</span>}
            </label>

            <Select
                {...selectLabels}
                id={id}
                aria-label={typeof label === "string" ? label : undefined}
                className="mt-2"
                placeholder={t("pleaseSelect")}
                options={options
                    .filter((option) => option?.value != null && option.value !== "")
                    .map((option) => ({ value: option.value, label: option.label }))}
                value={value === "" || value == null ? null : value}
                onChange={(v) => {
                    if (v != null) onChange(v);
                }}
            />

            {error && (
                <p className="bisheng-tip mt-1">
                    {t("fieldCannotBeEmpty", { label })}
                </p>
            )}
        </div>
    );
};
