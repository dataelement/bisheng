import { Button, Input } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";

import { generateUUID } from "@/components/bs-ui/utils";
import { useState } from "react";
import {
  DragDropContext,
  Draggable,
  Droppable,
  type DropResult,
} from "@hello-pangea/dnd";
import { useTranslation } from "react-i18next";
export const ruleI18nMap: Record<string, string> = {
  "\\n": "singleNewlineRule",
  "\\n\\n": "doubleNewlineRule",
  [String.fromCodePoint(0x7b2c) + ".{1,3}" + String.fromCodePoint(0x7ae0)]:
    "chapterRule",
  [String.fromCodePoint(0x7b2c) + ".{1,3}" + String.fromCodePoint(0x6761)]:
    "articleRule",
  [String.fromCodePoint(0x3002)]: "chinesePeriodRule",
  "\\.": "englishPeriodRule",
};

const predefinedRules = [
  { key: "singleNewlineRule", mode: "after" },
  { key: "doubleNewlineRule", mode: "after" },
  { key: "chapterRule", mode: "before" },
  { key: "articleRule", mode: "before" },
  { key: "chinesePeriodRule", mode: "after" },
  { key: "englishPeriodRule", mode: "after" },
] as const;

export interface SplitStrategy {
  id: string;
  regex: string;
  position: "before" | "after";
  rule: string;
}
interface FileUploadSplitStrategyProps {
  data: SplitStrategy[];
  onChange: (strategies: SplitStrategy[], added?: boolean) => void;
  disabled?: boolean;
  pending?: string;
  onPendingChange?: (value: string) => void;
  pendingPosition?: SplitStrategy["position"];
  onPositionChange?: (value: SplitStrategy["position"]) => void;
}

const DragHandleIcon = () => (
  <div className="grid h-4 w-4 grid-cols-2 gap-x-[3px] gap-y-[1px] text-[#94a3b8]">
    {Array.from({ length: 6 }).map((_, index) => (
      <span key={index} className="h-[2px] w-[2px] rounded-full bg-current" />
    ))}
  </div>
);

const FileUploadSplitStrategy = ({
  data: strategies,
  onChange: setStrategies,
  disabled = false,
  pending,
  onPendingChange,
  pendingPosition,
  onPositionChange,
}: FileUploadSplitStrategyProps) => {
  const { t } = useTranslation("knowledge");
  const [customRegex, setCustomRegex] = useState("");
  const [localPosition, setPosition] =
    useState<SplitStrategy["position"]>("after");
  const position = pendingPosition ?? localPosition;
  const input = pending ?? customRegex;

  const handleDragEnd = (result: DropResult) => {
    if (
      disabled ||
      !result.destination ||
      result.destination.index === result.source.index
    )
      return;

    const items = Array.from(strategies);
    const [reorderedItem] = items.splice(result.source.index, 1);
    items.splice(result.destination.index, 0, reorderedItem);

    setStrategies(items);
  };

  const handleAddCustomStrategy = () => {
    if (!disabled && input.trim()) {
      const newStrategy = {
        id: generateUUID(6),
        regex: pending === undefined ? input.trim() : input,
        position,
        rule: t("customRule"),
      };
      setStrategies([...strategies, newStrategy], true);
      setCustomRegex("");
    }
  };

  const handleRegexClick = (key: string, mode: SplitStrategy["position"]) => {
    const newStrategy = {
      id: generateUUID(6),
      regex: t(`predefinedRules.${key}.label`),
      position: mode,
      rule: t(`predefinedRules.${key}.desc`),
    };
    setStrategies([...strategies, newStrategy]);
  };

  const handleDelete = (id: string) => {
    setStrategies(strategies.filter((item) => item.id !== id));
  };

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(360px,0.96fr)]">
      <div className="flex min-w-0 flex-col gap-5">
        <div className="space-y-3">
          <h3 className="text-sm font-medium text-[#374151]">
            {t("recommendedRules")}
          </h3>
          <div className="flex flex-wrap gap-2">
            {predefinedRules.map((rule, index) => {
              const regexDisplay = t(`predefinedRules.${rule.key}.label`);
              return (
                <Button
                  disabled={disabled}
                  key={index}
                  className="h-6 rounded-[7px] bg-[#f1f5f9] px-2.5 text-[#0f172a] shadow-sm hover:bg-[#e7edf8]"
                  variant="filled"
                  onClick={() => handleRegexClick(rule.key, rule.mode)}
                  color="default"
                >
                  {rule.mode === "before"
                    ? `✂️${regexDisplay}`
                    : `${regexDisplay}✂️`}
                </Button>
              );
            })}
          </div>
        </div>

        <div className="space-y-3">
          <h3 className="text-sm font-medium text-[#374151]">
            {t("addCustomRule")}
          </h3>
          <div className="flex items-center gap-3">
            <div className="flex min-w-0 flex-1 items-center gap-2">
              <span className="shrink-0 text-sm text-[#0f172a]">{t("in")}</span>
              <Input
                aria-label={t("addCustomRule")}
                disabled={disabled}
                value={input}
                onChange={(e) =>
                  pending === undefined
                    ? setCustomRegex(e.target.value)
                    : onPendingChange?.(e.target.value)
                }
                placeholder={t("enterRegex")}
                className={[
                  "min-w-0 flex-1",
                  "h-8 min-w-0 w-full border-[#ebecf0] bg-white",
                ]
                  .filter(Boolean)
                  .join(" ")}
              />
              <div className="inline-flex h-8 shrink-0 items-center rounded-[6px] bg-[#f8f8f8] p-[3px]">
                {(["before", "after"] as const).map((item) => (
                  <button
                    key={item}
                    type="button"
                    disabled={disabled}
                    aria-pressed={position === item}
                    className={`rounded-[4px] px-3 py-[2px] text-sm leading-[22px] transition-colors ${position === item ? "bg-primary/15 font-medium text-primary" : "text-[#818181]"}`}
                    onClick={() =>
                      pendingPosition === undefined
                        ? setPosition(item)
                        : onPositionChange?.(item)
                    }
                  >
                    {item === "before" ? t("before") : t("after")}
                  </button>
                ))}
              </div>
              <span className="shrink-0 text-sm text-[#0f172a]">
                {t("split")}
              </span>
              <Button
                disabled={disabled || !input.trim()}
                onClick={handleAddCustomStrategy}
                className="h-8 shrink-0 rounded-md border-[#ebecf0] bg-white px-4 text-[#070038]"
                variant="outlined"
                color="default"
              >
                {t("add")}
              </Button>
            </div>
          </div>
        </div>
      </div>

      <div className="min-w-0">
        <div className="mb-3 flex flex-wrap items-center gap-2 leading-none">
          <h3 className="text-sm font-medium text-[#374151]">
            {t("addedRules")}
          </h3>
          <p className="text-sm text-[#999]">{t("splitPriorityInfo")}</p>
        </div>
        <div className="max-h-[12.5rem] select-none overflow-y-auto pr-1">
          <DragDropContext onDragEnd={handleDragEnd}>
            <Droppable droppableId="strategies">
              {(provided) => (
                <div {...provided.droppableProps} ref={provided.innerRef}>
                  {strategies.map((strategy, index) => (
                    <Draggable
                      isDragDisabled={disabled}
                      key={strategy.id}
                      draggableId={strategy.id}
                      index={index}
                    >
                      {(provided) => (
                        <div
                          ref={provided.innerRef}
                          {...provided.draggableProps}
                          className="group my-1 flex h-8 items-center gap-2 rounded-[4px] border border-[#e4e8ee] bg-[#f2f5f8] px-[5px] py-px text-sm"
                        >
                          <div
                            {...provided.dragHandleProps}
                            className="flex h-5 w-5 shrink-0 cursor-grab items-center justify-center text-[#94a3b8] active:cursor-grabbing"
                          >
                            <DragHandleIcon />
                          </div>
                          <div className="flex min-w-0 flex-1 items-center gap-3 overflow-hidden">
                            <span className="shrink-0 text-sm leading-5 text-[#0f172a]">
                              {strategy.position === "before"
                                ? `✂️${strategy.regex.replace(/\n/g, "\\n")}`
                                : `${strategy.regex.replace(/\n/g, "\\n")}✂️`}
                            </span>
                            <span className="min-w-0 truncate text-sm text-[#4e5969]">
                              {strategy.rule}
                            </span>
                          </div>
                          <div className="flex items-center">
                            <Button
                              disabled={disabled}
                              variant="text"
                              color="default"
                              iconOnly
                              size="small"
                              aria-label={`${t("delete")} ${strategy.regex.replace(/\n/g, "\\n")}`}
                              onClick={() => handleDelete(strategy.id)}
                              className="opacity-0 group-hover:opacity-100 focus:opacity-100"
                            >
                              <Outlined.Delete />
                            </Button>
                          </div>
                        </div>
                      )}
                    </Draggable>
                  ))}

                  {strategies.length < 5 &&
                    Array(5 - strategies.length)
                      .fill(null)
                      .map((_, index) => (
                        <div
                          key={`placeholder-${index}`}
                          className="my-1 h-8 rounded-[4px] bg-[#f3f4f6] opacity-60"
                        />
                      ))}
                  {provided.placeholder}
                </div>
              )}
            </Droppable>
          </DragDropContext>
        </div>
      </div>
    </div>
  );
};

export default FileUploadSplitStrategy;
