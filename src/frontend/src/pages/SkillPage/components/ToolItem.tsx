import { TitleIconBg } from "@/components/bs-comp/cardComponent";
import { ToolIcon } from "@/components/bs-icons/tool";
import {
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/bs-ui/accordion";
import { Button } from "@/components/bs-ui/button";
import { useTranslation } from "react-i18next";

export default function ToolItem({
  type,
  select,
  data,
  onEdit = (id) => {},
  onSelect,
}) {
  const { t } = useTranslation();

  return (
    <AccordionItem
      key={data.id}
      value={data.id}
      className="data-[state=open]:rounded-md data-[state=open]:border-2 data-[state=open]:border-primary/20"
    >
      <AccordionTrigger>
        <div className="relative flex gap-2 pr-4 text-start">
          <TitleIconBg className="h-8 w-8 min-w-8" id={data.id}>
            <ToolIcon />
          </TitleIconBg>
          <div>
            <p className="text-sm font-medium leading-none">
              {data.name}
              {type === "edit" && (
                <Button
                  size="sm"
                  className="ml-4 h-6"
                  onClick={(e) => onEdit(data.id)}
                >
                  Edit
                </Button>
              )}
            </p>
            <p className="mt-2 text-sm text-muted-foreground">
              {data.description}
            </p>
          </div>
        </div>
      </AccordionTrigger>
      <AccordionContent className="">
        <div className="mb-4 px-6">
          {data.children.map((api) => (
            <div key={api.name} className="relative rounded-sm border-t  p-4">
              <h1 className="text-sm font-medium leading-none">{api.name}</h1>
              <p className="mt-2 text-sm text-muted-foreground">{api.desc}</p>
              <p className="mt-2 flex gap-2 text-sm text-muted-foreground">
                <span>{t("build.params")}</span>:
                {api.api_params.map((param) => (
                  <div key={param.name}>
                    <span className=" rounded-xl bg-gray-200 px-2 py-1 text-xs font-medium text-white">
                      {param.name}
                    </span>
                    {/* <span>{param.schema.type}</span> */}
                  </div>
                ))}
              </p>
              {select &&
                (select.some((_) => _.id === api.id) ? (
                  <Button
                    size="sm"
                    className="absolute bottom-2 right-4 h-6"
                    disabled
                  >
                    {t("build.added")}
                  </Button>
                ) : (
                  <Button
                    size="sm"
                    className="absolute bottom-2 right-4 h-6"
                    onClick={() => onSelect(api)}
                  >
                    {t("build.add")}
                  </Button>
                ))}
            </div>
          ))}
        </div>
      </AccordionContent>
    </AccordionItem>
  );
}
