import { Button, Select } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import { useTranslation } from "react-i18next";
import { useSelectLabels } from "@/components/bs-comp/formFields/useSelectLabels";

interface KnowledgeSpaceCatalogFilterProps {
  hasAbnormal: boolean;
  onChange: (value: boolean) => void;
}

export function KnowledgeSpaceCatalogFilter({ hasAbnormal, onChange }: KnowledgeSpaceCatalogFilterProps) {
  const { t } = useTranslation("knowledge");
  const selectLabels = useSelectLabels();
  return (
    <Select
      {...selectLabels}
      options={[
        { label: t("fileStatusFilterAll"), value: "all" },
        { label: t("fileStatusAbnormal"), value: "abnormal" },
      ]}
      value={hasAbnormal ? "abnormal" : "all"}
      onChange={(value) => onChange(value === "abnormal")}
      trigger={(
        <Button
          variant="text"
          color={hasAbnormal ? "primary" : "default"}
          iconOnly
          aria-label={t("fileStatusFilterLabel", {
            value: t(hasAbnormal ? "fileStatusAbnormal" : "fileStatusFilterAll"),
          })}
        >
          <Outlined.Filter aria-hidden />
        </Button>
      )}
    />
  );
}
