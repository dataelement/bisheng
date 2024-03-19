import { Listbox } from "@headlessui/react"
import { CheckIcon, ChevronsUpDown } from "lucide-react"
import { useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import { Button } from "../../../components/ui/button"
import { getRolesApi, getUserRoles, updateUserRoles } from "../../../controllers/API/user"
import { ROLE } from "../../../types/api/user"
import { captureAndAlertRequestErrorHoc } from "../../../controllers/request"

export default function UserRoleModal({ id, onClose, onChange }) {
    const { t } = useTranslation()

    const [roles, setRoles] = useState<ROLE[]>([])
    const [selected, setSelected] = useState([])
    const [error, setError] = useState(false)

    useEffect(() => {
        if (!id) return
        getRolesApi().then(data => {
            const roleOptions = data.filter(role => role.id !== 1)
                .map(role => ({ ...role, role_id: role.id }))
            setRoles(roleOptions);

            getUserRoles(id).then(userRoles => {
                // 默认设置 普通用户
                if (!userRoles.find(role => role.role_id === 2)) {
                    const roleByroles = roleOptions.find(role => role.role_id === 2)
                    userRoles.unshift({ ...roleByroles })
                }
                setSelected(userRoles)
            })
        })
        setError(false)
    }, [id])

    function compareDepartments(a, b) {
        return a.role_id === b.role_id
    }

    const handleSave = async () => {
        if (!selected.length) return setError(true)
        const res = await captureAndAlertRequestErrorHoc(updateUserRoles(id, selected.map(item => item.role_id)))
        console.log('res :>> ', res);
        onChange()
    }

    return <dialog className={`modal ${id && 'modal-open'}`}>
        <div className="modal-box w-[600px] max-w-[600px] bg-[#fff] shadow-lg dark:bg-background relative overflow-visible">
            <p className="font-bold mt-8 mb-2">{t('system.roleSelect')}</p>
            <Listbox multiple
                value={selected}
                onChange={setSelected}
                by={compareDepartments} >
                <div className="relative mt-1">
                    <Listbox.Button className={`relative w-full cursor-default rounded-lg bg-white py-2 pl-3 pr-10 text-left shadow-md focus:outline-none border sm:text-sm h-[38px] ${error && 'border-red-400'}`}>
                        <div className="block truncate">{selected.map(el => el.role_name).join(';')}</div>
                        <span className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2">
                            <ChevronsUpDown />
                        </span>
                    </Listbox.Button>

                    <Listbox.Options className="absolute mt-1 max-h-60 w-full overflow-auto rounded-md bg-white py-1 text-base shadow-lg ring-1 ring-black ring-opacity-5 focus:outline-none sm:text-sm">
                        {roles.map((role, personIdx) => (
                            <Listbox.Option
                                key={role.role_id}
                                className={({ active }) =>
                                    `relative select-none py-2 pl-10 pr-4
                                    ${active
                                        ? 'bg-blue-100 text-gray-700'
                                        : 'text-gray-900 bg-gray-50 dark:bg-gray-900 dark:text-gray-100'} 
                                    ${role.role_id === 2
                                        ? 'cursor-not-allowed text-gray-300'
                                        : "cursor-default"}`
                                }
                                value={role}
                                disabled={role.role_id === 2}
                            >
                                {({ selected }) => (
                                    <>
                                        <span className={`block truncate ${selected ? 'font-medium' : 'font-normal'}`} >
                                            {role.role_name}
                                        </span>
                                        {selected ? (
                                            <span className="absolute inset-y-0 left-0 flex items-center pl-3 text-blue-600">
                                                <CheckIcon className="h-5 w-5" aria-hidden="true" />
                                            </span>
                                        ) : null}
                                    </>
                                )}
                            </Listbox.Option>
                        ))}
                    </Listbox.Options>
                </div>
            </Listbox>
            <div className="mt-12 flex justify-center gap-4">
                <Button variant="outline" className="px-16 rounded-full" onClick={onClose}>{t('cancel')}</Button>
                <Button className="px-16 rounded-full" onClick={handleSave}>{t('save')}</Button>
            </div>
        </div>
    </dialog>
};
