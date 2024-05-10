import { Button } from "@/components/bs-ui/button";
import { Dialog, DialogTrigger } from "@/components/bs-ui/dialog";
import { Input } from "@/components/bs-ui/input";
import { Table, TableBody, TableCell, TableFooter, TableHead, TableHeader, TableRow } from "@/components/bs-ui/table";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/bs-ui/tooltip";
import { useDiffFlowStore } from "@/store/diffFlowStore";
import { DownloadIcon, PlayIcon, QuestionMarkCircledIcon } from "@radix-ui/react-icons";
import { useMemo, useRef, useState } from "react";
import CellWarp from "./Cell";
import RunForm from "./RunForm";
import { DelIcon } from "@/components/bs-icons/del";
import * as XLSX from 'xlsx';
import { useTranslation } from "react-i18next";

export default function RunTest({ nodeId }) {

    const { t } = useTranslation()
    const [formShow, setFormShow] = useState(false)
    const { runningType, mulitVersionFlow, readyVersions, questions, removeQuestion, cellRefs,
        allRunStart, rowRunStart, colRunStart, overQuestions, addQuestion } = useDiffFlowStore()

    // 是否展示表单
    const isForm = useMemo(() => {
        const flowData = mulitVersionFlow?.[0]?.data
        if (!flowData) return false

        return flowData.nodes.some(node => ["VariableNode", "InputFileNode"].includes(node.data.type))
    }, [mulitVersionFlow])

    const handleUploadTxt = () => {
        const input = document.createElement("input");
        input.type = "file";
        input.accept = ".txt";
        input.onchange = (e: Event) => {
            if (
                (e.target as HTMLInputElement).files[0].type === "text/plain"
            ) {
                const currentfile = (e.target as HTMLInputElement).files[0];
                currentfile.text().then((text) => {
                    console.log(text, "text");
                    overQuestions(text.split('\n'))
                });
            }
        };
        input.click();
    }

    const { message } = useToast()
    const inputsRef = useRef(null)
    const handleRunTest = (inputs = null, query = '') => {
        setFormShow(false)
        inputsRef.current = { id: nodeId, query, data: inputs }
        //
        if (questions.length === 0) return message({
            title: t('prompt'),
            description: t('test.addTest'),
            variant: 'warning'
        })
        allRunStart(nodeId, inputsRef.current)
    }

    const handleColRunTest = (versionId) => {
        colRunStart(versionId, nodeId, inputsRef.current)
    }

    const handleRowRunTest = (qIndex) => {
        rowRunStart(qIndex, nodeId, inputsRef.current)
    }

    // 导出结果（excle）
    const handleDownExcle = () => {
        const data = [['测试用例', ...mulitVersionFlow.map(version => version.name)]];

        questions.forEach((_, index) => {
            const rowData = [_.q]
            mulitVersionFlow.forEach(version => {
                rowData.push(cellRefs[`${index}-${version.id}`].current.getData())
            })
            data.push(rowData)
        })
        mulitVersionFlow

        // 创建Workbook对象
        const wb = XLSX.utils.book_new();
        // 添加Worksheet到Workbook中
        const ws = XLSX.utils.aoa_to_sheet(data);
        XLSX.utils.book_append_sheet(wb, ws, "Sheet1");

        // 生成Excel文件
        const wbout = XLSX.write(wb, { bookType: 'xlsx', type: 'array' });
        const blob = new Blob([wbout], { type: 'application/octet-stream' });
        // 创建下载链接
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "test_result.xlsx";

        // 模拟点击下载链接
        document.body.appendChild(a);
        a.click();

        // 清理URL对象
        setTimeout(function () {
            document.body.removeChild(a);
            window.URL.revokeObjectURL(url);
        }, 0);
    }

    return <div className="mt-4 px-4">
        <div className="bg-[#fff] p-2">
            <div className="flex items-center justify-between ">
                <div className="flex gap-2 items-center">
                    <Button size="sm" onClick={handleUploadTxt}>{t('test.uploadTest')}</Button>
                    <TooltipProvider delayDuration={200}>
                        <Tooltip>
                            <TooltipTrigger asChild>
                                <QuestionMarkCircledIcon />
                            </TooltipTrigger>
                            <TooltipContent>
                                <p>{t('test.explain')}</p>
                            </TooltipContent>
                        </Tooltip>
                    </TooltipProvider>
                </div>
                {
                    isForm ? <Dialog open={formShow} onOpenChange={setFormShow}>
                        <DialogTrigger asChild>
                            <Button size="sm" disabled={runningType === 'all'}><PlayIcon />{t('test.testRun')}</Button>
                        </DialogTrigger>
                        <RunForm show={formShow} flow={mulitVersionFlow[0]} onChangeShow={setFormShow} onSubmit={handleRunTest} />
                    </Dialog> :
                        <Button size="sm" disabled={runningType === 'all'} onClick={() => handleRunTest()}><PlayIcon />{t('test.testRun')}</Button>
                }
            </div>
            {/* table */}
            <Table>
                <TableHeader>
                    <TableRow>
                        <TableHead className="w-[100px]">{t('test.testCase')}</TableHead>
                        {
                            mulitVersionFlow.map(version =>
                                version && <TableHead key={version.id}>
                                    <div className="flex items-center gap-2">
                                        <span>{version.name}</span>
                                        {readyVersions[version.id] && <Button
                                            disabled={['all', 'col'].includes(runningType)}
                                            size='icon'
                                            className="w-6 h-6"
                                            title={t('test.run')}
                                            onClick={() => handleColRunTest(version.id)}
                                        ><PlayIcon /></Button>}
                                    </div>
                                </TableHead>
                            )
                        }
                        <TableHead className="text-right">
                            <Button variant="link" disabled={runningType !== ''} onClick={handleDownExcle}><DownloadIcon className="mr-1" />{t('test.downloadResults')}</Button>
                        </TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {
                        questions.map((question, index) => (
                            <TableRow>
                                <TableCell>
                                    <div className="flex items-center gap-2 font-medium">
                                        {question.q}
                                        {question.ready && <Button
                                            disabled={['all', 'row'].includes(runningType)}
                                            size='icon'
                                            className="w-6 h-6"
                                            title="运行"
                                            onClick={() => handleRowRunTest(index)}
                                        ><PlayIcon /></Button>}
                                    </div>
                                </TableCell>
                                {/* 版本 */}
                                {mulitVersionFlow.map(flow =>
                                    flow && <TableCell key={flow.version + question.q}>
                                        <CellWarp qIndex={index} versionId={flow.id} />
                                    </TableCell>
                                )}
                                <TableCell className="text-right">
                                    <Button
                                        size="icon"
                                        variant="link"
                                        disabled={['all', 'row'].includes(runningType)}
                                        onClick={() => removeQuestion(index)}><DelIcon /></Button>
                                </TableCell>
                            </TableRow>
                        ))
                    }
                </TableBody>
                <TableFooter>
                    <TableRow>
                        {questions.length < 20 && <TableCell>
                            <div className="flex items-center gap-2 font-medium min-w-52">
                                <Input
                                    placeholder={t('test.testCases')}
                                    onKeyDown={(e) => {
                                        if (e.key === 'Enter') {
                                            if (!e.target.value) return
                                            addQuestion(e.target.value)
                                            e.target.value = ''
                                        }
                                    }}
                                    onBlur={(e) => {
                                        if (!e.target.value) return
                                        addQuestion(e.target.value)
                                        e.target.value = ''
                                    }} />
                            </div>
                        </TableCell>
                        }
                        <TableCell colSpan={4} className="text-right"></TableCell>
                    </TableRow>
                </TableFooter>
            </Table>
        </div>
    </div>
};
