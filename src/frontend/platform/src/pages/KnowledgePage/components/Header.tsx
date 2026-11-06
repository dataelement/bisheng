import { Outlined } from "bisheng-icons";
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
    <div className="z-30 flex min-h-14 items-start">
      {showBackButton && (
        <KnowledgeTooltip content={t("back")} side="top">
          <button
            className="extra-side-bar-buttons w-[36px]"
            aria-label={t("back")}
            onClick={handleBack}
          >
            <Outlined.ArrowLeft className="side-bar-button-size" />
          </button>
        </KnowledgeTooltip>
      )}
      {fileTitle && (
        <div>
          <span className="max-w-80 truncate pl-4 text-sm font-black text-foreground">
            {controlled ? (title ?? "") : legacyTitle}
          </span>
          {controlled && description && (
            <p className="text-hint max-w-80 truncate pl-4 text-xs">
              {description}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

export default Header;
