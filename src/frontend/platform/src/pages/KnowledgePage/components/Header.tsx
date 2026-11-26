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
  presentation?: "workspace";
}

export function Header({
  fileTitle,
  onBack,
  showBackButton = true,
  title,
  description,
  presentation,
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
          <h1 title={controlled ? (title ?? "") : legacyTitle} className={presentation === "workspace" ? "block max-w-full truncate text-base font-medium text-text-1" : "max-w-80 truncate pl-4 text-sm font-black text-foreground"}>
            {controlled ? (title ?? "") : legacyTitle}
          </h1>
          {controlled && description && (
            <p className={presentation === "workspace" ? "mt-1 max-w-full truncate text-xs text-text-3" : "text-hint max-w-80 truncate pl-4 text-xs"}>
              {description}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

export default Header;
