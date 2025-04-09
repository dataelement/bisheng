import { useState } from "react";
import { readOnlineFlows } from "../../../controllers/API/flow";
import { FlowType } from "../../../types/flow";
import { useTable } from "../../../util/hook";
import { Button } from "../../bs-ui/button";
import { SearchInput } from "../../bs-ui/input";
import {
  Sheet,
  SheetContent,
  SheetTitle,
  SheetTrigger,
} from "../../bs-ui/sheet";
import CardComponent from "../cardComponent";
import { useTranslation } from "react-i18next";

export default function SkillSheet({ select, children, onSelect }) {
  const [keyword, setKeyword] = useState("");
  const {
    data: onlineFlows,
    loading,
    search,
  } = useTable<FlowType>({}, (param) =>
    readOnlineFlows(param.page, param.keyword).then((res) => {
      return res;
    })
  );

  const handleSearch = (e) => {
    const { value } = e.target;
    setKeyword(value);
    search(value);
  };

  const toCreateFlow = () => {
    //@ts-ignore
    window.open(__APP_ENV__.BASE_URL + "/build/apps");
  };

  const { t } = useTranslation()

  return (
    <Sheet>
      <SheetTrigger asChild>{children}</SheetTrigger>
      <SheetContent className="sm:min-w-[966px]">
        <div className="flex h-full" onClick={(e) => e.stopPropagation()}>
          <div className="w-fit p-6">
            <SheetTitle>{t("build.addSkill")}</SheetTitle>
            <SearchInput
              value={keyword}
              placeholder={t("build.search")}
              className="my-6"
              onChange={handleSearch}
            />
            <Button className="w-full text-slate-50" onClick={toCreateFlow}>
              {t("build.createSkill")}
            </Button>
          </div>
          <div className="flex h-full min-w-[696px] flex-1 flex-wrap content-start gap-1.5 overflow-y-auto p-5 pt-12 scrollbar-hide">
            {onlineFlows[0] ? (
              onlineFlows.map((flow, i) => (
                <CardComponent
                  key={i}
                  id={i + 1}
                  data={flow}
                  logo={flow.logo}
                  title={flow.name}
                  description={flow.description}
                  type="sheet"
                  footer={
                    <div className="flex justify-end">
                      {select.some((_) => _.id === flow.id) ? (
                        <Button size="sm" className="h-6" disabled>
                          {t("build.added")}
                        </Button>
                      ) : (
                        <Button
                          size="sm"
                          className="h-6"
                          onClick={() => onSelect(flow)}
                        >
                          {t("build.add")}
                        </Button>
                      )}
                    </div>
                  }
                />
              ))
            ) : (
              <div className="flex w-full flex-col items-center justify-center pt-40">
                <p className="mb-3 text-sm text-muted-foreground">
                  {t("build.empty")}
                </p>
                <Button className="w-[200px]" onClick={toCreateFlow}>
                  {t("build.createSkill")}
                </Button>
              </div>
            )}
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}
