import { Listbox, Transition } from "@headlessui/react"
import { Fragment, useState } from "react"
import { Button } from "../../../components/ui/button"
import { CheckIcon, ChevronsUpDown } from "lucide-react"

export default function UserRoleModal({ id, onClose, onChange }) {

    const people = [
        { id: 1, name: '管理员' },
        { id: 2, name: '系统管理原' },
        { id: 3, name: '角色1' },
        { id: 4, name: '角色2' }
    ]

    const [selected, setSelected] = useState([people[0]])

    function compareDepartments(a, b) {
        return a.id === b.id
    }

    const handleSave = () => {
        console.log('selected :>> ', selected);
        onChange()
    }

    return <dialog className={`modal ${id && 'modal-open'}`}>
        <div className="modal-box w-[600px] max-w-[600px] bg-[#fff] shadow-lg dark:bg-background relative overflow-visible">
            <p className="font-bold mt-8 mb-2">角色选择</p>
            <Listbox multiple
                value={selected}
                onChange={setSelected}
                by={compareDepartments} >
                <div className="relative mt-1">
                    <Listbox.Button className="relative w-full cursor-default rounded-lg bg-white py-2 pl-3 pr-10 text-left shadow-md focus:outline-none border sm:text-sm">
                        <div className="block truncate">{selected.map(el => el.name).join(';')}</div>
                        <span className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2">
                            <ChevronsUpDown />
                        </span>
                    </Listbox.Button>

                    <Listbox.Options className="absolute mt-1 max-h-60 w-full overflow-auto rounded-md bg-white py-1 text-base shadow-lg ring-1 ring-black ring-opacity-5 focus:outline-none sm:text-sm">
                        {people.map((person, personIdx) => (
                            <Listbox.Option
                                key={person.id}
                                className={({ active }) =>
                                    `relative cursor-default select-none py-2 pl-10 pr-4 ${active ? 'bg-blue-100 text-gray-700' : 'text-gray-900 bg-gray-50'
                                    }`
                                }
                                value={person}
                            >
                                {({ selected }) => (
                                    <>
                                        <span className={`block truncate ${selected ? 'font-medium' : 'font-normal'}`} >
                                            {person.name}
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
                <Button variant="outline" className="px-16 rounded-full" onClick={onClose}>取消</Button>
                <Button className="px-16 rounded-full" onClick={handleSave}>保存</Button>
            </div>
        </div>
    </dialog>
};
