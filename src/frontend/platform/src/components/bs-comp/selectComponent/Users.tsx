import DepartmentUsersSelect, { type DepartmentUserOption } from "./DepartmentUsersSelect"

interface UsersSelectProps {
  multiple?: boolean
  lockedValues?: (number | string)[]
  value: DepartmentUserOption[]
  disabled?: boolean
  onChange: (value: DepartmentUserOption[]) => void
}

export default function UsersSelect({ multiple = false, lockedValues = [], value, disabled = false, onChange }: UsersSelectProps) {
  const mappedValue = (value || []).map(option => ({
    ...option,
    value: Number(option.value),
    external_id: option.external_id ?? null,
  })).filter(option => option.label && Number.isFinite(option.value))

  return <DepartmentUsersSelect multiple={multiple} value={mappedValue} lockedValues={lockedValues.map(Number)} disabled={disabled} onChange={onChange} />
}
