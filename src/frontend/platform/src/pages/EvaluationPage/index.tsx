// @ts-strict-ignore
import { Pagination, Button } from '@bisheng/ui';

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/bs-ui/table";

import { useNavigate } from "react-router-dom";

import { checkSassUrl } from "@/components/bs-comp/FileView";
import { LoadingIcon } from "@/components/bs-icons/loading";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { Tag, Tooltip } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import { usePaginationLocale } from "@/hooks/usePaginationLocale";

import {
  Evaluation,
  deleteEvaluationApi,
  getEvaluationApi,
  getEvaluationUrlApi,
} from "@/controllers/API/evaluate";
import { handleUiRequest } from "@/controllers/request";
import { useTable } from "@/util/hook";
import { downloadFile } from "@/util/utils";
import { map } from "lodash-es";

import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import {
  EvaluationScore,
  EvaluationScoreLabelMap,
  EvaluationStatusEnum,
  EvaluationStatusLabelMap,
  EvaluationType,
  EvaluationTypeLabelMap,
} from "./types";

export default function EvaluationPage() {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const paginationLocale = usePaginationLocale();

  const {
    page,
    pageSize,
    data: datalist,
    total,
    loading,
    setPage,
    reload,
  } = useTable({ cancelLoadingWhenReload: true }, (param) =>
    getEvaluationApi(param.page, param.pageSize)
  );

  useEffect(() => {
    const intervalId = setInterval(() => {
      reload();
    }, 6000); // Poll every 6 seconds

    return () => clearInterval(intervalId);
  }, [reload]);

  const handleDelete = (id) => {
    bsConfirm({
      title: t("prompt"),
      desc: t("evaluation.confirmDeleteEvaluation"),
      onOk(next) {
        return deleteEvaluationApi(id).then(() => {
            reload();
            next();
          });
      },
    });
  };

  const handleDownload = async (el) => {
    const { url } = await getEvaluationUrlApi(el.result_file_path);
    await downloadFile(checkSassUrl(url), el.file_name);
  };

  return (
    <div className="relative h-full w-full px-2 py-4">
      {loading && (
        <div className="absolute left-0 top-0 z-10 flex h-full w-full items-center justify-center bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
          <LoadingIcon />
        </div>
      )}
      <div className="h-full overflow-y-auto pb-10">
        <div className="mb-10 w-full">
            <div className="mr-2 flex items-center justify-end gap-4">
              <Button onClick={() => navigate("/evaluation/create")}>
                {t("create")}
              </Button>
            </div>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="min-w-[60px]">
                    {t("evaluation.id")}
                  </TableHead>
                  <TableHead className="min-w-[100px]">
                    {t("evaluation.filename")}
                  </TableHead>
                  <TableHead>{t("evaluation.skillAssistant")}</TableHead>
                  <TableHead className="w-[80px]">
                    {t("evaluation.status")}
                  </TableHead>
                  <TableHead className="w-[310px]">
                    {t("evaluation.score")}
                  </TableHead>
                  <TableHead className="min-w-[160px]">
                    {t("createTime")}
                  </TableHead>
                  <TableHead className="text-right">
                    {t("operations")}
                  </TableHead>
                </TableRow>
              </TableHeader>

              <TableBody>
                {datalist.map((el: Evaluation) => (
                  <TableRow key={el.id}>
                    <TableCell className="font-medium">{el.id}</TableCell>
                    <TableCell>{el.file_name || "--"}</TableCell>
                    <TableCell>
                      <div className="flex items-center">
                        <Tag size="small" className="whitespace-nowrap shrink-0">
                          {t(EvaluationTypeLabelMap[EvaluationType[el.exec_type]]?.label ?? t("unknown"))}
                        </Tag>
                        &nbsp;
                        <span className="whitespace-nowrap text-medium-indigo">
                          {el.unique_name}
                        </span>
                        &nbsp;
                        <span className="ml-1 whitespace-nowrap text-medium-indigo">
                          {el.version_name}
                        </span>
                      </div>
                    </TableCell>

                    <TableCell>
                      {!!el.status && (
                        <div className="flex items-center gap-1">
                          <Tag size="small" className="whitespace-nowrap shrink-0" dot color={EvaluationStatusLabelMap[el.status]?.color ?? "default"}>
                            {t(EvaluationStatusLabelMap[el.status]?.label ?? t("unknown"))}
                            {el.status === EvaluationStatusEnum.running
                              ? ` ${el.progress}`
                              : null}
                          </Tag>
                            {el.status === EvaluationStatusEnum.failed && (
                              <Tooltip content={el.description || t("description")} side="top">
                                <span tabIndex={0} className="inline-flex" aria-label={el.description || t("description")}>
                                  <Outlined.Question size={14} className="text-text-3" />
                                </span>
                              </Tooltip>
                            )}
                        </div>
                      )}
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-wrap">
                        {el.result_score
                          ? map(el.result_score, (value, key) => {
                            const labelKey = EvaluationScoreLabelMap[EvaluationScore[key]]?.label;
                            const displayLabel = labelKey ? t(labelKey) : key;
                            return (
                              <span key={key} className="whitespace-nowrap">
                                {displayLabel}
                                :{value}&nbsp;
                              </span>
                            );
                          })
                          : "-"}
                      </div>
                    </TableCell>
                    <TableCell>
                      {el.create_time.replace("T", " ") || "--"}
                    </TableCell>
                    <TableCell className="flex justify-end">
                      <div className="flex gap-2">
                        {el.status !== EvaluationStatusEnum.failed && <Button size="small" variant="link" onClick={handleUiRequest(() => handleDownload(el))}>
                          {t("evaluation.download")}
                        </Button>}
                        <Button size="small" variant="link" color="danger" onClick={() => handleDelete(el.id)}>
                          {t("delete")}
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
      </div>
      <div className="bisheng-table-footer px-6 bg-background-login">
        <div className="ml-auto">
          <Pagination locale={paginationLocale}
            current={page}
            pageSize={pageSize}
            total={total}
            onChange={(newPage) => setPage(newPage)}
          />
        </div>
      </div>
    </div>
  );
}
