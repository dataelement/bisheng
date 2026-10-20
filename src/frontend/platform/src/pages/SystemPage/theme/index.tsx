// @ts-strict-ignore
import { Button } from '@bisheng/ui';

import { saveThemeApi } from "@/controllers/API";
import { RadioGroup, Radio as RadioGroupItem } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";

import { useState } from "react";
import Example from "./Example";
import HSLitem from "./HSLitem";

import { Label } from "@/components/bs-ui/label";
import { Tabs } from "@bisheng/ui";
import { useTranslation } from "react-i18next";
import BrandCustomization from "./BrandCustomization";
import WorkbenchThemeSettings from "./WorkbenchThemeSettings";

// Default theme configuration
const defaultTheme = {
  "--background": { h: 0, s: 0, l: 1 },
  "--foreground": { h: 222.2, s: 0.474, l: 0.112 },
  "--muted": { h: 210, s: 0.4, l: 0.98 },
  "--muted-foreground": { h: 215.4, s: 0.163, l: 0.469 },
  "--popover": { h: 0, s: 0, l: 1 },
  "--popover-foreground": { h: 222.2, s: 0.474, l: 0.112 },
  "--card": { h: 0, s: 0, l: 1 },
  "--card-foreground": { h: 222.2, s: 0.474, l: 0.112 },
  "--border": { h: 214.3, s: 0.218, l: 0.914 },
  "--input": { h: 223, s: 0.48, l: 0.44 },
  "--primary": { h: 220, s: 0.98, l: 0.45 },
  "--primary-foreground": { h: 210, s: 0.4, l: 0.98 },
  "--secondary": { h: 210, s: 0.4, l: 0.961 },
  "--secondary-foreground": { h: 222.2, s: 0.474, l: 0.112 },
  "--accent": { h: 210, s: 0.3, l: 0.961 },
  "--accent-foreground": { h: 222.2, s: 0.474, l: 0.112 },
  "--destructive": { h: 0, s: 1, l: 0.5 },
  "--destructive-foreground": { h: 210, s: 0.4, l: 0.98 },
  "--black-button": { h: 0, s: 0, l: 0.07 },
};

// Theme key mappings for internationalization
const themeKeys = {
  "--primary": "theme.primary",
  "--primary-foreground": "theme.primaryForeground",
  "--background": "theme.background",
  "--foreground": "theme.foreground",
  "--muted": "theme.muted",
  "--muted-foreground": "theme.mutedForeground",
  "--card": "theme.card",
  "--card-foreground": "theme.cardForeground",
  "--popover": "theme.popover",
  "--popover-foreground": "theme.popoverForeground",
  "--border": "theme.border",
  "--input": "theme.input",
  "--secondary": "theme.secondary",
  "--secondary-foreground": "theme.secondaryForeground",
  "--accent": "theme.accent",
  "--accent-foreground": "theme.accentForeground",
  "--destructive": "theme.destructive",
  "--destructive-foreground": "theme.destructiveForeground",
  "--ring": "theme.ring",
  "--radius": "theme.radius",
  "--warning": "theme.warning",
  "--warning-foreground": "theme.warningForeground",
  "--black-button": "theme.blackButton",
};

function ThemeColorSettings() {
  const [theme, setTheme] = useState(
    Object.keys(window.ThemeStyle.comp).length ? window.ThemeStyle.comp : { ...defaultTheme },
  );
  const [bg, setBg] = useState(window.ThemeStyle.bg || "logo");
  const { t } = useTranslation();
  const applyTheme = (theme) => {
    Object.keys(theme).forEach((key) => {
      document.documentElement.style.setProperty(key, handleHSLtoStr(theme[key]));
    });
    setTheme(theme);
    window.ThemeStyle = { comp: theme, bg };
    saveThemeApi(JSON.stringify({ comp: theme }));
  };

  // hsl -> '220 98% 95%'
  const handleHSLtoStr = (hsl) => {
    return `${hsl.h} ${hsl.s * 100}% ${hsl.l * 100}%`;
  };

  const handleHSLChange = (name, hsl) => {
    const newTheme = {
      ...theme,
      [name]: hsl,
    };
    setTheme(newTheme);
    document.documentElement.style.setProperty(name, handleHSLtoStr(hsl));
    // Save the updated theme
    window.ThemeStyle = { comp: newTheme, bg };
    saveThemeApi(JSON.stringify({ comp: newTheme }));
  };

  return (
    <div className="flex justify-center border-t bg-accent">
      <div className="w-96 py-4 pr-8 border-r ">
        <p className="flex justify-between items-center mb-4">
          <span className="text-lg">{t("theme.colorConfig")}</span>
          <Button className="right" variant="link" onClick={(e) => applyTheme({ ...defaultTheme })}>
            <Outlined.Refresh className="mr-1 size-4" />
            {t("theme.restoreDefault")}
          </Button>
        </p>
        <div className="grid grid-cols-2 gap-2 gap-x-8 my-8">
          {Object.keys(theme).map((key) => {
            return (
              <HSLitem key={key} label={t(themeKeys[key])} name={key} value={theme[key]} onChange={handleHSLChange} />
            );
          })}
        </div>
        <p className="flex justify-between items-center mb-4">
          <span className="text-lg">{t("theme.workflowBackgroundConfig")}</span>
        </p>
        <RadioGroup
          value={bg}
          onValueChange={(val) => {
            window.ThemeStyle.bg = val;
            saveThemeApi(JSON.stringify({ comp: theme, bg: val }));
            setBg(val);
          }}
          className="flex space-x-2 h-[20px] mt-4 mb-6"
        >
          <div>
            <Label className="flex justify-center">
              <RadioGroupItem className="mr-2" value="logo" />
              {t("theme.bishengLogo")}
            </Label>
          </div>
          <div>
            <Label className="flex justify-center">
              <RadioGroupItem className="mr-2" value="gradient" />
              {t("theme.themeColorGradientEffect")}
            </Label>
          </div>
        </RadioGroup>
      </div>
      <div className="px-4 py-4 bg-card">
        <p className="text-xl mb-4">{t("theme.componentPreview")}</p>
        <div>
          {/* Component list */}
          <Example />
        </div>
      </div>
    </div>
  );
}

export default function Theme() {
  const { t } = useTranslation();

  return (
    <Tabs
      defaultActiveKey="brand"
      className="flex h-full min-h-0 flex-1 flex-col [&>div:first-child]:shrink-0 [&>[role=tabpanel][data-state=active]]:flex [&>[role=tabpanel]]:min-h-0 [&>[role=tabpanel]]:flex-1 [&>[role=tabpanel]]:flex-col [&>[role=tabpanel]]:overflow-hidden [&>[role=tabpanel]>div]:mt-2"
      items={[
        {
          key: "brand",
          label: <> {t("theme.brandCustomization")} </>,
          children: (
            <>
              {" "}
              <div className="min-h-0 flex-1 overflow-hidden">
                <BrandCustomization />
              </div>
            </>
          ),
        },
        {
          key: "workbench",
          label: <> {t("theme.workbenchTheme")} </>,
          children: (
            <>
              {" "}
              <div className="min-h-0 flex-1 overflow-auto">
                <WorkbenchThemeSettings />
              </div>
            </>
          ),
        },
        {
          key: "themeColor",
          label: <> {t("theme.adminTheme")} </>,
          children: (
            <>
              {" "}
              <div className="min-h-0 flex-1 overflow-auto">
                <ThemeColorSettings />
              </div>
            </>
          ),
        },
      ]}
    />
  );
}
