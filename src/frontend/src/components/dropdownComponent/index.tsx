import { useContext, useEffect, useState } from "react";
import { PopUpContext } from "../../contexts/popUpContext";
import { DropDownComponentType } from "../../types/components";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "../bs-ui/select";

export default function Dropdown({
  value,
  options,
  onSelect,
  editNode = false
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
    <Select value={internalValue} onValueChange={(value) => {
      setInternalValue(value);
      onSelect(value);
    }}>
      <SelectTrigger className={editNode && 'h-7'}>
        <SelectValue placeholder="" />
      </SelectTrigger>
      <SelectContent>
        <SelectGroup>
          {options.map((option, id) => (
            <SelectItem key={id} value={option}>{option}</SelectItem>
          ))}
        </SelectGroup>
      </SelectContent>
    </Select>
  )
}
