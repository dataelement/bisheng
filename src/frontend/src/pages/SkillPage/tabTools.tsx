import { Accordion } from "@/components/bs-ui/accordion";
import { Button } from "@/components/bs-ui/button";
import { SearchInput } from "@/components/bs-ui/input";
import { getAssistantToolsApi } from "@/controllers/API/assistant";
import { PersonIcon, StarFilledIcon } from "@radix-ui/react-icons";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import EditTool from "./components/EditTool";
import ToolItem from "./components/ToolItem";

export default function tabTools({ select = null, onSelect }) {
  const [keyword, setKeyword] = useState(" ");
  const [allData, setAllData] = useState([]);
  const { t } = useTranslation()

  const [type, setType] = useState(""); // '' add edit
  const editRef = useRef(null);

  const loadData = (_type = "custom") => {
    getAssistantToolsApi(_type).then((res) => {
      setAllData(res);
      setKeyword("");
    });
  };
  useEffect(() => {
    loadData(type === "" ? "default" : "custom");
  }, [type]);

  const options = useMemo(() => {
    return allData.filter((el) =>
      el.name.toLowerCase().includes(keyword.toLowerCase())
    );
  }, [keyword, allData]);

  return (
    <div className="flex h-full relative" onClick={(e) => e.stopPropagation()}>
      <div className="w-full flex h-full overflow-y-scroll scrollbar-hide relative top-[-60px]">
        <div className="w-fit p-6">
          <h1>{t("tools.addTool")}</h1>
          <SearchInput
            placeholder={t("tools.search")}
            className="mt-6"
            onChange={(e) => setKeyword(e.target.value)}
          />
          <Button
            className="mt-4 w-full"
            onClick={() => editRef.current.open()}
          >
            {t('create')}{t("tools.createCustomTool")}
          </Button>
          <div className="mt-4">
            <div
              className={`flex cursor-pointer items-center gap-2 rounded-md px-4 py-2 transition-all duration-200 hover:bg-muted-foreground/10 ${type === "" && "bg-muted-foreground/10"
                }`}
              onClick={() => setType("")}
            >
              <PersonIcon />
              <span>{t("tools.builtinTools")}</span>
            </div>
            <div
              className={`mt-1 flex cursor-pointer items-center gap-2 rounded-md px-4 py-2 transition-all duration-200 hover:bg-muted-foreground/10 ${type === "edit" && "bg-muted-foreground/10"
                }`}
              onClick={() => setType("edit")}
            >
              <StarFilledIcon />
              <span>{t("tools.customTools")}</span>
            </div>
          </div>
        </div>
        <div className="h-full w-full flex-1 overflow-auto bg-[#fff] p-5 pt-12 scrollbar-hide">
          <Accordion type="single" collapsible className="w-full">
            {options.length ? (
              options.map((el) => (
                <ToolItem
                  key={el.id}
                  type={type}
                  select={select}
                  data={el}
                  onSelect={onSelect}
                  onEdit={(id) => editRef.current.edit(el)}
                ></ToolItem>
              ))
            ) : (
              <div className="mt-2 pt-40 text-center text-sm text-muted-foreground">
                {t("tools.empty")}
              </div>
            )}
          </Accordion>
        </div>
      </div>
      {/* footer */}
      <div className="absolute bottom-0 left-0 flex h-16 w-full items-center justify-between bg-[#F4F5F8] px-10">
        <p className="break-keep text-sm text-muted-foreground">
          {t("tools.manageCustomTools")}
        </p>
      </div>

      <EditTool onReload={() => {
        // 切换自定义工具 并 刷新
        setType('edit');
        type === 'edit' && loadData();
      }}
        ref={editRef} />
    </div>
  );
}
