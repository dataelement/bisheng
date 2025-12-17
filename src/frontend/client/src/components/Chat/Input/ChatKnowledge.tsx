import {
  FileText,
  GlobeIcon,
  Settings2Icon,
  Check,
  BookOpen,
  BookOpenText,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Switch } from "~/components/ui";
import { Select, SelectContent, SelectTrigger } from "~/components/ui/Select";
import { Input } from "~/components/ui/input";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "~/components/ui/Tooltip2";
import { cn } from "~/utils";
import { useLocalize } from "~/hooks";
import { useGetOrgToolList, useModelBuilding } from "~/data-provider";
import { BsConfig } from "~/data-provider/data-provider/src";

export const ChatKnowledge = ({
  config,
  disabled,
  searchType,
  setSearchType,
  enableOrgKb,
  setEnableOrgKb,
  selectedOrgKbs,
  setSelectedOrgKbs,
}: {
  config?: BsConfig;
  disabled: boolean;

  searchType: string;
  setSearchType: React.Dispatch<React.SetStateAction<string>>;
  selectedPersonalKbIds: string[];
  setSelectedPersonalKbIds: React.Dispatch<React.SetStateAction<string[]>>;

  enableOrgKb: boolean;
  setEnableOrgKb: (v: boolean) => void;
  selectedOrgKbs: string[];
  setSelectedOrgKbs: React.Dispatch<React.SetStateAction<string[]>>;
}) => {
  const [building] = useModelBuilding();
  const localize = useLocalize();
  const MAX_ORG_KB = 50;

  const { data: orgTools } = useGetOrgToolList();

  const [keyword, setKeyword] = useState("");

  const filteredList = useMemo(() => {
    if (!orgTools) return [];

    return orgTools.filter((item) => item.name?.includes(keyword));
  }, [orgTools, keyword]);

  const toggleOrgKb = (kb: { id: string; name: string }) => {
    setSelectedOrgKbs((prev) => {
      const exists = prev.some((i) => i.id === kb.id);

      if (exists) {
        return prev.filter((i) => i.id !== kb.id);
      }

      if (prev.length >= MAX_ORG_KB) {
        return prev;
      }

      return [{ id: kb.id, name: kb.name }, ...prev];
    });
  };

  useEffect(() => {
    setSelectedOrgKbs([]);
  }, []);

  return (
    <Select disabled={disabled}>
      <SelectTrigger className="h-7 rounded-full px-2 bg-white data-[state=open]:border-blue-500">
        <div className="flex gap-2">
          <BookOpenText size={16} />
          <span className="text-xs">
            {localize("com_tools_knowledge_base")}
          </span>
        </div>
      </SelectTrigger>

      <SelectContent className="bg-white rounded-xl p-3 w-60">
        {/* ===== 个人知识库 ===== */}
        {config?.knowledgeBase.enabled && (
          <div className="flex justify-between">
            <div className="flex gap-2 items-center">
              <BookOpen size={16} />
              <span className="text-xs">
                {localize("com_tools_personal_knowledge")}
              </span>
            </div>
            <Tooltip delayDuration={200}>
              <TooltipTrigger>
                <Switch
                  className="data-[state=checked]:bg-blue-600"
                  disabled={building || disabled}
                  checked={searchType === "knowledgeSearch"}
                  onCheckedChange={(val) => {
                    if (searchType === "knowledgeSearch") {
                      setSearchType("");
                    } else {
                      setSearchType("knowledgeSearch");
                    }
                  }}
                />
              </TooltipTrigger>
              {building && (
                <TooltipContent>
                  {localize("com_tools_knowledge_rebuilding")}
                </TooltipContent>
              )}
            </Tooltip>
          </div>
        )}

        <div className="flex justify-between items-center mt-3">
          <div className="flex gap-2 items-center">
            <img
              className="size-5 pr-1"
              src={__APP_ENV__.BASE_URL + "/assets/books.png"}
              alt=""
            />
            <span className="text-xs">
              {localize("com_tools_org_knowledge")}
            </span>
          </div>
          <Switch
            checked={enableOrgKb}
            onCheckedChange={setEnableOrgKb}
            disabled={disabled}
            className="data-[state=checked]:bg-blue-600"
          />
        </div>

        {enableOrgKb && (
          <>
            <Input
              className="mt-3 h-7 text-xs"
              placeholder={localize("com_tools_knowledge_base_search")}
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
            />
            {filteredList.map((item) => {
              const checked = selectedOrgKbs.some((kb) => kb.id === item.id);
              return (
                <div
                  key={item.id}
                  onClick={() => toggleOrgKb(item)}
                  className="flex justify-between items-center px-4 py-1.5 rounded cursor-pointer text-xs hover:bg-slate-100"
                >
                  <span>{item.name}</span>
                  {checked && <Check size={14} className="text-blue-600" />}
                </div>
              );
            })}
          </>
        )}
      </SelectContent>
    </Select>
  );
};
