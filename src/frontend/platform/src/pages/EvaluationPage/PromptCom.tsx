import { Button } from '@bisheng/ui';
import { useContext, useEffect, useState } from "react";
import { PopUpContext } from "@/contexts/popUpContext";
import GenericModal from "@/modals/genericModal";
import { TextAreaComponentType } from "@/types/components";
import { TypeModal } from "@/utils";

import { Outlined } from "bisheng-icons";

import { useTranslation } from "react-i18next";

export default function PromptAreaComponent({
  field_name,
  setNodeClass,
  nodeClass,
  value,
  onChange,
  disabled,
  editNode = false,
  type = TypeModal.PROMPT,
}: TextAreaComponentType) {
  const { t } = useTranslation();
  const [myValue, setMyValue] = useState(value);
  const { openPopUp } = useContext(PopUpContext);
  useEffect(() => {
    if (disabled) {
      setMyValue("");
      onChange("");
    }
  }, [disabled, onChange]);

  const handleSave = (t: string) => {
    setMyValue(t);
    onChange(t);
  };

  return (
    <div className={disabled ? "pointer-events-none w-full " : "w-full"}>
      <div className="flex w-full items-center">
        <span
          onClick={() => {
            openPopUp(
              <GenericModal
                type={type}
                value={myValue}
                buttonText={t("code.checkAndSave")}
                modalTitle={t("evaluation.editPrompt")}
                setValue={(t: string) => {
                  setMyValue(t);
                  onChange(t);
                }}
                nodeClass={nodeClass}
                setNodeClass={setNodeClass}
              />
            );
          }}
          className={
            editNode
              ? "input-edit-node input-dialog"
              : (disabled ? " input-disable text-ring " : "") +
                " whitespace-wrap input-primary"
          }
        >
          {myValue !== "" ? myValue : t("evaluation.enterPrompt")}
        </span>
        <Button type="button" variant="text" size="medium" aria-label={t("evaluation.editPrompt")} onClick={() => {
            openPopUp(
              <GenericModal
                field_name={field_name}
                type={TypeModal.PROMPT}
                value={myValue}
                buttonText={t("code.checkAndSave")}
                modalTitle={t("evaluation.editPrompt")}
                setValue={handleSave}
                nodeClass={nodeClass}
                setNodeClass={setNodeClass}
              />
            );
          }} color="default" iconOnly>
          {!editNode && (
            <Outlined.ExpandTextInput size={16} />
          )}
        </Button>
      </div>
    </div>
  );
}
