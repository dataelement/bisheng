import { Listbox, Transition } from "@headlessui/react";
import { Check, ChevronsUpDown } from "lucide-react";
import { Fragment, useContext, useEffect, useState } from "react";
import { PopUpContext } from "../../contexts/popUpContext";
import { DropDownComponentType } from "../../types/components";
import { classNames } from "../../utils";

export default function Dropdown({
  value,
  options,
  onSelect,
  editNode = false,
  numberOfOptions = 0,
  apiModal = false,
}: DropDownComponentType) {
  const { closePopUp } = useContext(PopUpContext);

  let [internalValue, setInternalValue] = useState(
    value === "" || !value ? "" : value
  );

  useEffect(() => {
    setInternalValue(value === "" || !value ? "" : value);
  }, [closePopUp]);

  useEffect(() => {
    if (internalValue !== value) {
      setInternalValue(value)
    }
  }, [value])

  return (
    <>
      <Listbox
        value={internalValue}
        onChange={(value) => {
          setInternalValue(value);
          onSelect(value);
        }}
      >
        {({ open }) => (
          <>
            <div className={editNode ? "mt-1" : "relative mt-1" + ' col-span-3'}>
              <Listbox.Button
                className={
                  editNode
                    ? "dropdown-component-outline min-h-[38px]"
                    : "dropdown-component-false-outline min-h-[38px]"
                }
              >
                <span className="dropdown-component-display">
                  {internalValue}
                </span>
                <span className={"dropdown-component-arrow"}>
                  <ChevronsUpDown
                    className="dropdown-component-arrow-color"
                    aria-hidden="true"
                  />
                </span>
              </Listbox.Button>

              <Transition
                show={open}
                as={Fragment}
                leave="transition ease-in duration-100"
                leaveFrom="opacity-100"
                leaveTo="opacity-0"
              >
                <Listbox.Options
                  className={classNames(
                    editNode
                      ? "dropdown-component-true-options nowheel custom-scroll"
                      : "dropdown-component-false-options nowheel custom-scroll",
                    apiModal ? "mb-2 w-[250px]" : "absolute"
                  )}
                >
                  {options.map((option, id) => (
                    <Listbox.Option
                      key={id}
                      className={({ active }) =>
                        classNames(
                          active ? " bg-accent" : "",
                          editNode
                            ? "dropdown-component-false-option"
                            : "dropdown-component-true-option"
                        )
                      }
                      value={option}
                    >
                      {({ selected, active }) => (
                        <>
                          <span
                            className={classNames(
                              selected ? "font-semibold" : "font-normal",
                              "block truncate "
                            )}
                          >
                            {option}
                          </span>

                          {selected ? (
                            <span
                              className={classNames(
                                active ? "text-background " : "",
                                "dropdown-component-choosal"
                              )}
                            >
                              <Check
                                className={
                                  active
                                    ? "dropdown-component-check-icon"
                                    : "dropdown-component-check-icon"
                                }
                                aria-hidden="true"
                              />
                            </span>
                          ) : null}
                        </>
                      )}
                    </Listbox.Option>
                  ))}
                </Listbox.Options>
              </Transition>
            </div>
          </>
        )}
      </Listbox>
    </>
  );
}
