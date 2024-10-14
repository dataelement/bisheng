import { Button } from "@/components/bs-ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/bs-ui/table";
import { Tabs, TabsContent } from "@/components/bs-ui/tabs";
import { useNavigate } from "react-router-dom";

import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { Badge } from "@/components/bs-ui/badge";
import AutoPagination from "@/components/bs-ui/pagination/autoPagination";
import {
  Evaluation,
  deleteEvaluationApi,
  getEvaluationApi,
  getEvaluationUrlApi,
} from "@/controllers/API/evaluate";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
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
import { checkSassUrl } from "@/components/bs-comp/FileView";
import { LoadingIcon } from "@/components/bs-icons/loading";

export default function EvaluationPage() {
  const navigate = useNavigate();
  const { t } = useTranslation();

  const {
    page,
    pageSize,
    data: datalist,
    total,
    loading,
    setPage,
    search,
    reload,
  } = useTable({ cancelLoadingWhenReload: true }, (param) =>
    getEvaluationApi(param.page, param.pageSize)
  );

  useEffect(() => {
    const intervalId = setInterval(() => {
      reload();
    }, 6000); // 每 6 秒轮询一次

    return () => clearInterval(intervalId);
  }, [reload]);

  const handleDelete = (id) => {
    bsConfirm({
      title: t("prompt"),
      desc: t("evaluation.confirmDeleteEvaluation"),
      onOk(next) {
        captureAndAlertRequestErrorHoc(
          deleteEvaluationApi(id).then((res) => {
            reload();
          })
        );
        next();
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
        <Tabs defaultValue="account" className="mb-[40px] w-full">
          <TabsContent value="account">
            <div className="flex items-center justify-end gap-4">
              <Button
                className="px-8 text-[#fff]"
                onClick={() => navigate("/evaluation/create")}
              >
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
                        <Badge className="whitespace-nowrap">
                          {
                            t(EvaluationTypeLabelMap[EvaluationType[el.exec_type]]
                              .label)
                          }
                        </Badge>
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
                        <Badge
                          variant={EvaluationStatusLabelMap[el.status].variant}
                          className={"whitespace-nowrap"}
                        >
                          {t(EvaluationStatusLabelMap[el.status].label)}
                          {el.status === EvaluationStatusEnum.running
                            ? ` ${el.progress}`
                            : null}
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-wrap">
                        {el.result_score
                          ? map(el.result_score, (value, key) => {
                            return (
                              <span className="whitespace-nowrap">
                                {
                                  EvaluationScoreLabelMap[
                                    EvaluationScore[key]
                                  ].label
                                }
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
                    <TableCell className="text-right">
                      <div className="flex">
                        <Button
                          variant="link"
                          className="no-underline hover:underline"
                          onClick={() => handleDownload(el)}
                        >
                          {t("evaluation.download")}
                        </Button>
                        <Button
                          variant="link"
                          onClick={() => handleDelete(el.id)}
                          className="ml-1 px-0 text-red-500"
                        >
                          {t("delete")}
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TabsContent>
          <TabsContent value="password"></TabsContent>
        </Tabs>
      </div>
      <div className="bisheng-table-footer px-6 bg-background-login">
        <p className="desc">{t("evaluation.evaluationCollection")}</p>
        <div>
          <AutoPagination
            page={page}
            pageSize={pageSize}
            total={total}
            onChange={(newPage) => setPage(newPage)}
          />
        </div>
      </div>
    </div>
  );
}
