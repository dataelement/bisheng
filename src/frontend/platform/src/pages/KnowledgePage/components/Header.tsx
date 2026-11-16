import { Outlined } from "bisheng-icons";
import { Button } from "@bisheng/ui";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { KnowledgeTooltip } from "./KnowledgeTooltip";

interface HeaderProps {
  fileTitle: boolean;
  onBack?: () => void;
  showBackButton?: boolean;
  title?: string;
  description?: string;
}

export function Header({
  fileTitle,
  onBack,
  showBackButton = true,
  title,
  description,
}: HeaderProps) {
  const { t } = useTranslation("knowledge");
  const navigate = useNavigate();
  const controlled = title !== undefined || description !== undefined;
  const [legacyTitle, setLegacyTitle] = useState("");
  useEffect(() => {
    if (controlled) return;
    // Legacy consumers retain their old title contract; SPACE always supplies props.
    const remembered = (window as Window & { libname?: unknown }).libname;
    const [name, desc] = Array.isArray(remembered) ? remembered : [];
    if (typeof name === "string" && name) {
      localStorage.setItem("libname", name);
      localStorage.setItem("libdesc", typeof desc === "string" ? desc : "");
    }
    setLegacyTitle(
      typeof name === "string" && name
        ? name
        : (localStorage.getItem("libname") ?? ""),
    );
  }, [controlled]);
  const handleBack = () => {
    if (onBack) onBack();
    else if (window.history.length > 1) navigate(-1);
    else navigate("/filelib");
  };

  return (
    <div className="flex min-w-0 items-center gap-3">
      {showBackButton && (
        <KnowledgeTooltip content={t("back")} side="top">
          <Button
            variant="text"
            color="default"
            iconOnly
            className="shrink-0"
            aria-label={t("back")}
            onClick={handleBack}
          >
            <Outlined.ArrowLeft />
          </Button>
        </KnowledgeTooltip>
      )}
      {fileTitle && (
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-h3 text-text-1" title={controlled ? (title ?? "") : legacyTitle}>
            {controlled ? (title ?? "") : legacyTitle}
          </h1>
          {controlled && description && (
            <p className="mt-1 truncate text-body-sm text-text-3" title={description}>
              {description}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

export default Header;
