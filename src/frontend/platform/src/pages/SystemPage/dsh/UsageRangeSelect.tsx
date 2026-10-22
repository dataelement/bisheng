import { Button } from '@bisheng/ui';

import { Popover, PopoverContent, PopoverTrigger } from "@/components/bs-ui/popover";
import { Outlined } from "bisheng-icons";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { usagePresetRange, type UsagePreset, type UsageRange } from "./usageRange";

interface UsageRangeSelectProps {
  preset: UsagePreset;
  onChange: (preset: UsagePreset, range: UsageRange) => void;
}

export function UsageRangeSelect({ preset, onChange }: UsageRangeSelectProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  return (
    <Popover open={open} onOpenChange={setOpen} modal={false}>
      <PopoverTrigger asChild>
        <Button variant="outlined" className="min-w-32 justify-between" aria-label={t("dsh.usageRange")} color="default">
          {t(`dsh.range.${preset}`)}
          <Outlined.Down className="ml-2 size-4 opacity-60" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80 max-w-[calc(100vw-2rem)] space-y-2 p-2">
        {(["today", "30d", "year"] as const).map((item) => (
          <Button key={item} variant="text" className="w-full justify-start" onClick={() => {
              onChange(item, usagePresetRange(item));
              setOpen(false);
            }} color="default">
            {t(`dsh.range.${item}`)}
          </Button>
        ))}
      </PopoverContent>
    </Popover>
  );
}
