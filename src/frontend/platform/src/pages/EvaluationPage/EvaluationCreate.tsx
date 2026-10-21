// @ts-strict-ignore
import { Button, Input, notification } from '@bisheng/ui';
import { Tooltip } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";


import { Label } from "@/components/bs-ui/label";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/bs-ui/select";

import { AppHint as QuestionTooltip } from "@/pages/BuildPage/components/AppHint";
import { TabsContext } from "@/contexts/tabsContext";
import { createEvaluationApi } from "@/controllers/API/evaluate";
import { getAppsApi } from "@/controllers/API/flow";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { TypeModal } from "@/utils";
import { SelectViewport } from "@radix-ui/react-select";
import { debounce, find } from "lodash-es";

import { useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { useDropzone } from "react-dropzone";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";
import PromptAreaComponent from "./PromptCom";
import defaultPrompt from "./defaultPrompt";

export default function EvaluatingCreate() {
  const { t } = useTranslation();

  const { id } = useParams();
  const { flow: nextFlow } = useContext(TabsContext);

  const flow = useMemo(() => {
    return id ? nextFlow : null;
  }, [id, nextFlow]);
  const [selectedType, setSelectedType] = useState<"workflow" | "assistant" | "flow" | "">("");
  const [selectedKeyId, setSelectedKeyId] = useState("");
  const [selectedVersion, setSelectedVersion] = useState("");
  const [query, setQuery] = useState("");
  const [dataSource, setDataSource] = useState([]);
  const [prompt, setPrompt] = useState(defaultPrompt);
  const [fileName, setFileName] = useState("");

  const [loading, setLoading] = useState(false);
  const fileRef = useRef(null);

  const onDrop = (acceptedFiles) => {
    const file = acceptedFiles[0];
    if (!file) return;

    const fileExt = file.name.split('.').pop()?.toLowerCase();


    fileRef.current = acceptedFiles[0];
    const size = fileRef.current.size
    const errorlist = [];

    // 1. File extension validation (double insurance)
    if (fileExt !== 'csv') {
      errorlist.push(t("evaluation.onlyCsvAllowed"));
      fileRef.current = null;
      handleError(errorlist);
      return;
    }

    // File size limit: 10M max
    if (size > 10 * 1024 * 1024) {
      errorlist.push(t("evaluation.fileSizeLimit"));
      fileRef.current = null
      return handleError(errorlist);
    }

    const names = acceptedFiles[0].name;
    setFileName(names);
  };

  const { getRootProps, getInputProps } = useDropzone({
    // Precise matching of CSV MIME types and extensions to avoid file bypass
    accept: {
      "text/csv": [".csv"],          // Standard CSV text type
      "application/csv": [".csv"],   // CSV application type recognized by some browsers
      "application/vnd.ms-excel": [".csv"] // Compatible with CSV exported from old Excel versions
    },
    useFsAccessApi: false,
    onDrop,
    maxFiles: 1,
    onDropRejected: (files) => {
      if (files.length > 0) {
        // Check rejected file types
        const rejectedFile = files[0];
        const fileExt = rejectedFile.file.name.split('.').pop()?.toLowerCase();

        if (fileExt === 'xlsx' || fileExt === 'xls') {
          handleError([t("evaluation.excelNotSupported")]);
        } else {
          handleError([t("evaluation.onlyCsvSupported")]);
        }
      }
    }
  });

  const navigate = useNavigate();

  const handleCreateEvaluation = async () => {
    const errorlist = [];
    if (!selectedType) errorlist.push(t("evaluation.enterExecType"));

    if (selectedType && !selectedKeyId) {
      if (selectedType === "workflow") errorlist.push(t("evaluation.selectWorkflow"));
      if (selectedType === "flow") errorlist.push(t("evaluation.selectSkill"));
      if (selectedType === "assistant") errorlist.push(t("evaluation.selectAssistant"));
    }

    if (selectedKeyId && (selectedType === "workflow" || selectedType === "flow") && !selectedVersion) {
      errorlist.push(t("evaluation.selectVersion"));
    }
    if (
      !fileRef.current &&
      selectedKeyId &&
      (
        (selectedType === "workflow" || selectedType === "flow") && selectedVersion // Types with versions selected
        || selectedType === "assistant" // Types that don't need versions
      )
    ) {
      errorlist.push(t("evaluation.enterFile"));
    }
    if (!prompt) errorlist.push(t("evaluation.enterPrompt"));

    if (errorlist.length) return handleError(errorlist);
    setLoading(true);
    try {
      const formData = new FormData();
      formData.append('exec_type', selectedType);       // Execution type
      formData.append('unique_id', selectedKeyId);     // Unique ID
      formData.append('version', selectedVersion);     // Version number
      formData.append('prompt', prompt);               // Prompt text

      if (fileRef.current) {
        formData.append('file', fileRef.current); // Key name 'file' must match backend
      }
      await captureAndAlertRequestErrorHoc(
        createEvaluationApi(formData)
      )

      navigate(-1);
    } finally {
      setLoading(false);
    }
  };

  const handleError = (list) => {
    notification.open({ type: "error", description: String(list ?? '') });
  };

  // Type selection
  const handleTypeChange = (type) => {
    setQuery("");
    if (type) {
      // Compatible with old names
      const typeMap = {
        workflow: 'flow',
        assistant: 'assistant',
        flow: 'skill'
      };

      getAppsApi({
        // F027: cursor-based; first page = no cursor.
        pageSize: 100,
        keyword: "",
        type: typeMap[type],
      }).then((response) => {
        setDataSource(response.data);
      });
    }
  };

  const handleDownloadTemplate = () => {
    const link = document.createElement("a");
    link.href = __APP_ENV__.BASE_URL + "/template.csv"; // File path
    link.download = "template.csv"; // Download filename
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const handleSearch = useCallback(debounce((value) => {
    if (selectedType) {
      // Compatible with old names
      const typeMap = {
        workflow: 'flow',
        assistant: 'assistant',
        flow: 'skill'
      };

      getAppsApi({
        // F027: cursor-based; first page = no cursor.
        pageSize: 100,
        keyword: value,
        type: typeMap[selectedType],
      }).then((response) => {
        setDataSource(response.data);
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
          <Tooltip content={t("back")} side="right">
            <Button variant="text" size="medium" aria-label={t("back")} onClick={() => navigate(-1)} color="default" iconOnly>
              <Outlined.ArrowLeft size={16} />
            </Button>
          </Tooltip>
        </div>
        {/* Form */}
        <div className="pt-6">
          <p className="text-center text-2xl">{t("evaluation.createTitle")}</p>
          <div className="mx-auto mt-4 w-full max-w-3xl">
            {/* Base form */}
            <div className="w-full overflow-hidden px-1 transition-all space-y-8">
              <div className="flex items-center justify-between gap-1">
                <Label className="w-[180px] text-right">
                  {t("evaluation.selectLabel")}
                </Label>
                <div className="flex flex-1 gap-2">
                  <Select
                    value={selectedType}
                    onValueChange={(value) => {
                      setSelectedType(value as typeof selectedType);
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
                        {/* <SelectItem value="flow">{t("build.skill")}</SelectItem> */}
                        <SelectItem value="assistant">{t("build.assistant")}</SelectItem>
                        <SelectItem value="workflow">{t("build.workFlow")}</SelectItem>
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
                      <Input value={query} onChange={handleInputChange} autoFocus placeholder={t("evaluation.selectInputPlaceholder")} onKeyDown={(e) => e.stopPropagation()} className={"my-2 mx-auto"} />
                      <SelectViewport className="h-80">
                        <SelectGroup>
                          {dataSource.filter(item => item.id != null && item.id !== '').map((item) => {
                            return (
                              <SelectItem key={item.id} value={item.id}>
                                {item.name}
                              </SelectItem>
                            );
                          })}
                        </SelectGroup>
                      </SelectViewport>
                    </SelectContent>
                  </Select>
                  {(selectedType === "workflow" || selectedType === "flow") && (
                    <Select
                      value={selectedVersion}
                      onValueChange={(version) => setSelectedVersion(version)}
                      onOpenChange={() => {
                        if (!selectedKeyId) {
                          if (selectedType === "workflow") {
                            return handleError([t("evaluation.selectWorkflow")]);
                          } else if (selectedType === "flow") {
                            return handleError([t("evaluation.selectSkill")]);
                          }
                        }
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
                          })?.version_list?.filter(item => item.id != null && item.id !== '').map((item) => {
                            return (
                              <SelectItem key={item.id} value={item.id}>
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
              <div className="flex items-center gap-1">
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
                    <Button type="button" variant="outlined" size="small" color="default">
                      <Outlined.Upload size={14} />
                      <span className="whitespace-nowrap">
                        {t("code.uploadFile")}
                      </span>
                    </Button>
                    {fileName && (
                      <div className="ml-2 truncate">{fileName}</div>
                    )}
                    <Label className="whitespace-nowrap">
                      &nbsp;{t("evaluation.fileExpandName")}&nbsp;csv
                    </Label>
                  </div>
                  <Button className="ml-2" variant="link" onClick={handleDownloadTemplate}>
                    {t("evaluation.downloadTemplate")}
                  </Button>
                </div>
              </div>
              <div className="flex items-center justify-between gap-1">
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

              <div className="flex">
                <div className="min-w-[180px]"></div>
                <div className="flex flex-1 gap-4">
                  <Button disabled={loading} className="extra-side-bar-save-disable flex-1" onClick={handleCreateEvaluation}>
                    {t("evaluation.create")}
                  </Button>
                  <Button disabled={loading} className="flex-1" variant="outlined" onClick={() => navigate(-1)} color="default">
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
