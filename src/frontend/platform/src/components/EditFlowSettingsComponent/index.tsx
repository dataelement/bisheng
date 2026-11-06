import { Input, Textarea } from '@bisheng/ui';
import React, { ChangeEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { Label } from "../../components/bs-ui/label";

type InputProps = {
  name: string | null;
  description: string | null;
  maxLength?: number;
  setName: (name: string) => void;
  setDescription: (description: string) => void;
};

export const EditFlowSettings: React.FC<InputProps> = ({
  name,
  description,
  maxLength = 50,
  setName,
  setDescription
}) => {
  const { t } = useTranslation()
  const [isMaxLength, setIsMaxLength] = useState(false);

  const handleNameChange = (event: ChangeEvent<HTMLInputElement>) => {
    const { value } = event.target;
    setIsMaxLength(value.length >= maxLength);
    setName(value);
  };

  const handleDescriptionChange = (event: ChangeEvent<HTMLTextAreaElement>) => {
    setDescription(event.target.value);
  };

  return (
    <>
      <Label>
        <div className="edit-flow-arrangement">
          <span className="font-medium">{t('flow.skillName')}</span>{" "}
          {isMaxLength && (
            <span className="edit-flow-span">{t('flow.nameTooLong')}</span>
          )}
        </div>
        <Input onChange={handleNameChange} type="text" name="name" value={name ?? ""} placeholder="File name" id="name" maxLength={maxLength} showCount className={"mt-2 font-normal"} />
      </Label>
      <Label>
        <span className="font-medium">{t('flow.skillDescription')}</span>
        <Textarea name="description" id="description" onChange={handleDescriptionChange} value={description ?? ""} placeholder="Flow description" rows={3} textareaClassName={"mt-2 max-h-[100px] font-normal"} />
      </Label>
    </>
  );
};

export default EditFlowSettings;
