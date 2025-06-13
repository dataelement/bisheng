import React, { ChangeEvent, useState } from "react";
import { useTranslation } from "react-i18next";
import { Input, Textarea } from "../../components/bs-ui/input";
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
        <Input
          className="mt-2 font-normal"
          onChange={handleNameChange}
          type="text"
          name="name"
          value={name ?? ""}
          placeholder="File name"
          id="name"
          maxLength={maxLength}
          showCount
        />
      </Label>
      <Label>
        <span className="font-medium">{t('flow.skillDescription')}</span>
        <Textarea
          name="description"
          id="description"
          onChange={handleDescriptionChange}
          value={description ?? ""}
          placeholder="Flow description"
          className="mt-2 max-h-[100px] font-normal"
          rows={3}
        />
      </Label>
    </>
  );
};

export default EditFlowSettings;
