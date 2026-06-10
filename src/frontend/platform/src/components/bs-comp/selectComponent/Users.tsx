import DepartmentUsersSelect, { DepartmentUserOption } from "./DepartmentUsersSelect";

export default function UsersSelect({ multiple = false, lockedValues = [], value, disabled = false, onChange }:
    { multiple?: boolean, lockedValues?: any[], value: any, disabled?: boolean, onChange: (a: any) => any }) {
    const mappedValue: DepartmentUserOption[] = (value || []).map((v: any) => {
        const dp = v?.department_path
        return {
            label: String(v?.label ?? ''),
            value: Number(v?.value),
            department_id: v?.department_id == null ? undefined : Number(v.department_id),
            dept_id: typeof v?.dept_id === "string" ? v.dept_id : undefined,
            external_id: v?.external_id ?? null,
            department_path: typeof dp === "string" && dp.trim() ? dp.trim() : undefined,
        }
    }).filter((x) => x.label && Number.isFinite(x.value))

    return <DepartmentUsersSelect
        multiple={multiple}
        value={mappedValue}
        lockedValues={(lockedValues || []).map((x: any) => Number(x))}
        disabled={disabled}
        onChange={onChange}
    />
};
