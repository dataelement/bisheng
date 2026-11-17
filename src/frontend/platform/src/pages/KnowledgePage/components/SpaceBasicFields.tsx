import { Input, Textarea } from "@bisheng/ui";
import { useId, useRef } from "react";
import { useTranslation } from "react-i18next";
import {
  getSpaceTextLength,
  SPACE_DESCRIPTION_LIMIT,
  SPACE_NAME_LIMIT,
  truncateSpaceText,
} from "./spaceSettingsForm";

const LEGACY_SPACE_TEXT_LIMIT = 200;

export function isValidSpaceBasic(name: string, description: string) {
  return (
    name.trim().length > 0 &&
    name.length <= LEGACY_SPACE_TEXT_LIMIT &&
    description.length <= LEGACY_SPACE_TEXT_LIMIT
  );
}

interface SpaceBasicFieldsProps {
  name: string;
  description: string;
  onNameChange: (value: string) => void;
  onDescriptionChange: (value: string) => void;
  disabled: boolean;
  compact?: boolean;
  creating?: boolean;
}

export function SpaceBasicFields({
  name,
  description,
  onNameChange,
  onDescriptionChange,
  disabled,
  compact = false,
  creating = false,
}: SpaceBasicFieldsProps) {
  const { t } = useTranslation("knowledge");
  const id = useId();
  const nameComposing = useRef(false);
  const descriptionComposing = useRef(false);
  const fieldClassName = compact ? "space-y-2" : undefined;
  const labelClassName = compact
    ? "block text-body font-medium text-text-1"
    : "bisheng-label";
  return (
    <div className="space-y-4">
      <div className={fieldClassName}>
        <label htmlFor={`${id}-name`} className={labelClassName}>
          {compact && <span className="mr-1 text-danger" aria-hidden>*</span>}
          {t("f118.space_name")}
        </label>
        <Input
          id={`${id}-name`}
          value={name}
          placeholder={compact ? t("f118.space_name_placeholder") : undefined}
          disabled={disabled}
          required={compact}
          aria-describedby={creating ? `${id}-name-count` : undefined}
          suffix={
            creating ? (
              <span
                id={`${id}-name-count`}
                className="text-body-sm text-text-3"
              >
                {Math.ceil(getSpaceTextLength(name))}/{SPACE_NAME_LIMIT}
              </span>
            ) : undefined
          }
          onCompositionStart={() => {
            nameComposing.current = true;
          }}
          onCompositionEnd={(event) => {
            nameComposing.current = false;
            if (creating) {
              onNameChange(
                truncateSpaceText(event.currentTarget.value, SPACE_NAME_LIMIT),
              );
            }
          }}
          onChange={(event) => {
            const value = event.target.value;
            onNameChange(
              creating && !nameComposing.current
                ? truncateSpaceText(value, SPACE_NAME_LIMIT)
                : value,
            );
          }}
        />
      </div>
      <div className={fieldClassName}>
        <label htmlFor={`${id}-description`} className={labelClassName}>
          {t("f118.space_description")}
        </label>
        <Textarea
          id={`${id}-description`}
          value={description}
          placeholder={
            compact ? t("f118.space_description_placeholder") : undefined
          }
          disabled={disabled}
          onCompositionStart={() => {
            descriptionComposing.current = true;
          }}
          onCompositionEnd={(event) => {
            descriptionComposing.current = false;
            if (creating) {
              onDescriptionChange(
                truncateSpaceText(event.currentTarget.value, SPACE_DESCRIPTION_LIMIT),
              );
            }
          }}
          onChange={(event) => {
            const value = event.target.value;
            onDescriptionChange(
              creating && !descriptionComposing.current
                ? truncateSpaceText(value, SPACE_DESCRIPTION_LIMIT)
                : value,
            );
          }}
          rows={compact ? 3 : 8}
        />
      </div>
    </div>
  );
}
