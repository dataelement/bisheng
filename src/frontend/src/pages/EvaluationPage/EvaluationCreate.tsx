import { QuestionMarkIcon } from "@/components/bs-icons/questionMark";
import { UploadIcon } from "@/components/bs-icons/upload";
import { Input } from "@/components/bs-ui/input";
import { AssistantItemDB, getAssistantsApi } from "@/controllers/API/assistant";
import { createEvaluationApi } from "@/controllers/API/evaluate";
import { TypeModal } from "@/utils";
import { SelectViewport } from "@radix-ui/react-select";
import { debounce, find } from "lodash-es";
import { ArrowLeft } from "lucide-react";
import { useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { useDropzone } from "react-dropzone";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";
import ShadTooltip from "@/components/ShadTooltipComponent";
import { Button } from "@/components/bs-ui/button";
import { Label } from "@/components/bs-ui/label";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/bs-ui/select";
import {
  QuestionTooltip,
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/bs-ui/tooltip";
import { alertContext } from "@/contexts/alertContext";
import { TabsContext } from "@/contexts/tabsContext";
import { readFlowsFromDatabase } from "@/controllers/API/flow";
import PromptAreaComponent from "./PromptCom";
import defaultPrompt from "./defaultPrompt";
import { useToast } from "@/components/bs-ui/toast/use-toast";

export default function EvaluatingCreate() {
  const { t } = useTranslation();

  const { id } = useParams();
  const { flow: nextFlow } = useContext(TabsContext);
  const { toast } = useToast()
  const flow = useMemo(() => {
    return id ? nextFlow : null;
  }, [nextFlow]);
  const [selectedType, setSelectedType] = useState<"flow" | "assistant" | "">(
    ""
  );
  const [selectedKeyId, setSelectedKeyId] = useState("");
  const [selectedVersion, setSelectedVersion] = useState("");
  const [query, setQuery] = useState("");
  const [dataSource, setDataSource] = useState([]);
  const [prompt, setPrompt] = useState(defaultPrompt);
  const [fileName, setFileName] = useState("");

  const [loading, setLoading] = useState(false);
  const fileRef = useRef(null);

  const onDrop = (acceptedFiles) => {
    fileRef.current = acceptedFiles[0];
    const size = fileRef.current.size
    const errorlist = [];

    // 限制文件最大为 10M
    if (size > 10 * 1024 * 1024) {
      errorlist.push(t("evaluation.fileSizeLimit"));
      fileRef.current = null
      return handleError(errorlist);
    }

    const names = acceptedFiles[0].name;
    setFileName(names);
  };

  const { getRootProps, getInputProps } = useDropzone({
    accept: {
      "application/*": [".csv"],
    },
    useFsAccessApi: false,
    onDrop,
    maxFiles: 1,
  });

  const navigate = useNavigate();

  const handleCreateEvaluation = async () => {
    const errorlist = [];
    if (!selectedType) errorlist.push(t("evaluation.enterExecType"));
    if (!selectedKeyId) errorlist.push(t("evaluation.enterUniqueId"));
    if (selectedType === "flow" && !selectedVersion)
      errorlist.push(t("evaluation.enterVersion"));
    if (!fileRef.current) errorlist.push(t("evaluation.enterFile"));
    if (!prompt) errorlist.push(t("evaluation.enterPrompt"));

    if (errorlist.length) return handleError(errorlist);
    setLoading(true);
    try {
      await createEvaluationApi({
        exec_type: selectedType,
        unique_id: selectedKeyId,
        version: selectedVersion,
        prompt,
        file: fileRef.current,
      });
      navigate(-1);
    } finally {
      setLoading(false);
    }
  };

  const handleError = (list) => {
    toast({
      variant: "error",
      description: list
    });
  };

  // 助手技能发生变化
  const handleTypeChange = (type) => {
    setQuery("");
    if (type === "flow") {
      readFlowsFromDatabase(1, 100, "").then((_flow) => {
        setDataSource(_flow.data);
      });
    } else if (type === "assistant") {
      getAssistantsApi(1, 100, "").then((data) => {
        setDataSource((data as any).data as AssistantItemDB[]);
      });
    }
  };

  const handleDownloadTemplate = () => {
    const link = document.createElement("a");
    link.href = __APP_ENV__.BASE_URL + "/template.csv"; // 文件路径
    link.download = "template.csv"; // 下载时的文件名
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const handleSearch = useCallback(debounce((value) => {
    if (selectedType === "flow") {
      readFlowsFromDatabase(1, 100, value).then((_flow) => {
        setDataSource(_flow.data);
      });
    } else if (selectedType === "assistant") {
      getAssistantsApi(1, 100, value).then((data) => {
        setDataSource((data as any).data as AssistantItemDB[]);
      });
    }
  }, 300), [selectedType])

  const handleInputChange = (event) => {
    setQuery(event.target.value);
    handleSearch(event.target.value);
  };

  useEffect(() => {
    return () => {
      handleSearch.cancel();
    };
  }, [handleSearch]);

  return (
    <div className="relative box-border h-full overflow-auto">
      <div className="h-full overflow-y-auto p-6 pb-48">
        <div className="flex w-full justify-between">
          <ShadTooltip content={t("back")} side="right">
            <button
              className="extra-side-bar-buttons w-[36px]"
              onClick={() => navigate(-1)}
            >
              <ArrowLeft strokeWidth={1.5} className="side-bar-button-size" />
            </button>
          </ShadTooltip>
        </div>
        {/* form */}
        <div className="pt-6">
          <p className="text-center text-2xl">{t("evaluation.createTitle")}</p>
          <div className="mx-auto mt-4 w-full max-w-2xl">
            {/* base form */}
            <div className="w-full overflow-hidden px-1 transition-all">
              <div className="mt-4 flex items-center justify-between gap-1">
                <Label className="w-[180px] text-right">
                  {t("evaluation.selectLabel")}
                </Label>
                <div className="flex flex-1 gap-2">
                  <Select
                    value={selectedType}
                    onValueChange={(value) => {
                      setSelectedType(value as any);
                      setSelectedKeyId("");
                      handleTypeChange(value);
                    }}
                  >
                    <SelectTrigger>
                      <SelectValue
                        className="mt-2 w-auto"
                        placeholder={t("evaluation.selectPlaceholder")}
                      />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectGroup>
                        <SelectItem value="flow">{t("build.skill")}</SelectItem>
                        <SelectItem value="assistant">
                          {t("build.assistant")}
                        </SelectItem>
                      </SelectGroup>
                    </SelectContent>
                  </Select>
                  <Select
                    value={selectedKeyId}
                    onValueChange={(id) => setSelectedKeyId(id)}
                    onOpenChange={() => {
                      if (!selectedType)
                        return handleError([t("evaluation.enterExecType")]);
                    }}
                  >
                    <SelectTrigger slot="" className="max-w-[200px]">
                      <SelectValue
                        className="mt-2 max-w-[200px]"
                        placeholder={t("evaluation.selectPlaceholder")}
                      />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectViewport>
                        <Input
                          value={query}
                          onChange={handleInputChange}
                          className="my-2 mx-auto"
                          placeholder={t("evaluation.selectInputPlaceholder")}
                        />
                        <SelectGroup>
                          {dataSource.map((item) => {
                            return (
                              <SelectItem value={item.id}>
                                {item.name}
                              </SelectItem>
                            );
                          })}
                        </SelectGroup>
                      </SelectViewport>
                    </SelectContent>
                  </Select>
                  {selectedType === "flow" && (
                    <Select
                      value={selectedVersion}
                      onValueChange={(version) => setSelectedVersion(version)}
                      onOpenChange={() => {
                        if (!selectedKeyId)
                          return handleError([t("evaluation.enterUniqueId")]);
                      }}
                    >
                      <SelectTrigger className="min-w-[50px]">
                        <SelectValue
                          className="mt-2"
                          placeholder={t("evaluation.selectPlaceholder")}
                        />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectGroup>
                          {find(dataSource, {
                            id: selectedKeyId,
                          })?.version_list?.map((item) => {
                            return (
                              <SelectItem value={item.id}>
                                {item.name}
                              </SelectItem>
                            );
                          })}
                        </SelectGroup>
                      </SelectContent>
                    </Select>
                  )}
                </div>
              </div>
              <div className="mt-4 flex items-center gap-1">
                <div className="min-w-[180px] text-right">
                  <Label className="whitespace-nowrap">
                    {t("evaluation.dataLabel")}
                  </Label>
                </div>
                <div className="flex flex-1 items-center justify-between">
                  <div
                    {...getRootProps()}
                    className="flex w-0 flex-1 items-center"
                  >
                    <input {...getInputProps()} />
                    <div className="flex cursor-pointer items-center justify-center rounded-md border px-[12px] py-[6px] hover:border-primary">
                      <UploadIcon className="group-hover:text-primary" />
                      <span className="whitespace-nowrap">
                        {t("code.uploadFile")}
                      </span>
                    </div>
                    {fileName && (
                      <div className="ml-2 truncate">{fileName}</div>
                    )}
                    <Label className="whitespace-nowrap">
                      &nbsp;{t("evaluation.fileExpandName")}&nbsp;csv
                    </Label>
                  </div>
                  <Button
                    className="ml-2 w-[80px]"
                    variant="link"
                    onClick={handleDownloadTemplate}
                  >
                    {t("evaluation.downloadTemplate")}
                  </Button>
                </div>
              </div>
              <div className="mt-4 flex items-center justify-between gap-1">
                <div className="min-w-[180px] text-right">
                  <Label className="flex items-center justify-end">
                    <QuestionTooltip content={t("evaluation.tooltip")} />
                    {t("evaluation.promptLabel")}
                  </Label>
                </div>
                <div className="flex-1" style={{ width: "calc(100% - 180px)" }}>
                  <PromptAreaComponent
                    field_name={"prompt"}
                    editNode={false}
                    disabled={false}
                    type={TypeModal.TEXT}
                    value={prompt}
                    onChange={(t: string) => {
                      setPrompt(t);
                    }}
                  />
                </div>
              </div>

              <div className="mt-8 flex">
                <div className="min-w-[180px]"></div>
                <div className="flex flex-1 gap-4">
                  <Button
                    disabled={loading}
                    className="extra-side-bar-save-disable flex-1"
                    onClick={handleCreateEvaluation}
                  >
                    {t("evaluation.create")}
                  </Button>
                  <Button
                    disabled={loading}
                    className="flex-1"
                    variant="outline"
                    onClick={() => navigate(-1)}
                  >
                    {t("evaluation.cancel")}
                  </Button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
