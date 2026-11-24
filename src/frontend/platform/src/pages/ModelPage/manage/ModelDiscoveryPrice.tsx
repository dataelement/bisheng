import type { DiscoveredModel } from "@/controllers/API/modelDiscovery";
import { useTranslation } from "react-i18next";

const money = (currency: string, value: string) =>
  `${currency === "USD" ? "$" : "¥"}${value}`;

interface DiscoveredModelPriceProps {
  model: DiscoveredModel;
  // Rows with no catalog price say they will be added at 0 (free).
  showUnpriced: boolean;
}

/** F016: the catalog price that adding this model prefills. */
export function DiscoveredModelPrice({
  model,
  showUnpriced,
}: DiscoveredModelPriceProps) {
  const { t } = useTranslation("model");
  const { catalog } = model;
  if (!catalog && !showUnpriced) return null;
  return (
    <p className="truncate text-xs text-muted-foreground">
      {catalog
        ? t("model.catalogPrice", {
            label: catalog.label,
            input: money(catalog.currency, catalog.input),
            output: money(catalog.currency, catalog.output),
          })
        : t("model.catalogPriceMissing")}
    </p>
  );
}
