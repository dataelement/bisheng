import { DelIcon } from "@/components/bs-icons/del";
import { Button } from "@/components/bs-ui/button";
import { Dialog, DialogTrigger } from "@/components/bs-ui/dialog";
import { Input } from "@/components/bs-ui/input";
import { Table, TableBody, TableCell, TableFooter, TableHead, TableHeader, TableRow } from "@/components/bs-ui/table";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/bs-ui/tooltip";
import { generateUUID } from "@/components/bs-ui/utils";
import { postBuildInit } from "@/controllers/API";
import { useDiffFlowStore } from "@/store/diffFlowStore";
import { FlowStyleType, FlowType } from "@/types/flow";
import { CircleHelp, Download, Play } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import * as XLSX from 'xlsx';
import CellWarp from "./Cell";
import RunForm from "./RunForm";

export default function RunTest({ nodeId }) {

    const { t } = useTranslation()
    const [formShow, setFormShow] = useState(false)
    const { running, runningType, mulitVersionFlow, readyVersions, questions, removeQuestion, cellRefs,
        allRunStart, rowRunStart, colRunStart, overQuestions, addQuestion, updateQuestion } = useDiffFlowStore()

    // 是否展示表单
    const isForm = useMemo(() => {
        const flowData = mulitVersionFlow?.[0]?.data
        if (!flowData) return false

        return flowData.nodes.some(node => ["VariableNode", "InputFileNode"].includes(node.data.type))
    }, [mulitVersionFlow])

    // 选中的测试版本数
    const versionColWidth = useMemo(() => {
        const count = mulitVersionFlow.reduce((count, cur) => {
            return cur ? count + 1 : count
        }, 0) + 1 // +1 测试用例列 

        return 100 / (count === 2 ? count : count + 1) // hack 两个 按 45% 分
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
    const build = useBuild()
    const handleRunTest = async (inputs = null, query = '') => {
        setFormShow(false)
        const res = await build(mulitVersionFlow[0])
        // console.log('res  :>> ', res);
        const input = res.input_keys.find((el: any) => !el.type)
        const inputKey = input ? Object.keys(input)[0] : '';
        inputsRef.current = { ...input, id: nodeId, [inputKey]: query, data: inputs }
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

    const notDiffVersion = useMemo(() => !mulitVersionFlow.some((version) => version), [mulitVersionFlow])

    return <div className="mt-4 px-4">
        <div className="bg-[#fff] dark:bg-gray-950 p-2">
            <div className="flex items-center justify-between ">
                <div className="flex gap-2 items-center">
                    <Button size="sm" disabled={['all', 'row', 'col'].includes(runningType)} onClick={handleUploadTxt}>{t('test.uploadTest')}</Button>
                    <TooltipProvider delayDuration={200}>
                        <Tooltip>
                            <TooltipTrigger asChild>
                                <CircleHelp className="w-4 h-4" />
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
                            <Button size="sm" disabled={runningType === 'all' || notDiffVersion}><Play />{t('test.testRun')}</Button>
                        </DialogTrigger>
                        <RunForm show={formShow} flow={mulitVersionFlow[0]} onChangeShow={setFormShow} onSubmit={handleRunTest} />
                    </Dialog> :
                        <Button size="sm" disabled={runningType === 'all' || notDiffVersion} onClick={() => handleRunTest()}><Play />{t('test.testRun')}</Button>
                }
            </div>
            {/* table */}
            <Table className="table-fixed">
                <TableHeader>
                    <TableRow>
                        <TableHead style={{ width: `${versionColWidth}%` }}>{t('test.testCase')}</TableHead>
                        {
                            mulitVersionFlow.map(version =>
                                version && <TableHead key={version.id} style={{ width: `${versionColWidth + 10}%` }}>
                                    <div className="flex items-center gap-2">
                                        <span>{version.name}</span>
                                        {readyVersions[version.id] && <Button
                                            disabled={['all'].includes(runningType)}
                                            size='icon'
                                            className="w-6 h-6"
                                            title={t('test.run')}
                                            onClick={() => handleColRunTest(version.id)}
                                        ><Play /></Button>}
                                    </div>
                                </TableHead>
                            )
                        }
                        <TableHead className="text-right min-w-[135px]" style={{ width: 135 }}>
                            <Button variant="link" disabled={runningType !== '' || !running} onClick={handleDownExcle}><Download className="mr-1" />{t('test.downloadResults')}</Button>
                        </TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {
                        questions.map((question, index) => (
                            <TableRow>
                                <TableCell>
                                    <div className="flex items-center gap-2 font-medium">
                                        <Input
                                            disabled={['all', 'row'].includes(runningType)}
                                            placeholder={t('test.testCases')}
                                            value={question.q}
                                            onChange={(e) => updateQuestion(e.target.value, index)}
                                        ></Input>
                                        {question.ready && <Button
                                            disabled={['all'].includes(runningType) || notDiffVersion}
                                            size='icon'
                                            className="min-w-6 h-6"
                                            title="运行"
                                            onClick={() => handleRowRunTest(index)}
                                        ><Play /></Button>}
                                    </div>
                                </TableCell>
                                {/* 版本 */}
                                {mulitVersionFlow.map(flow =>
                                    flow && <TableCell key={index + '-' + flow.id} className=''>
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
                        <TableCell colSpan={5} className="text-right"></TableCell>
                    </TableRow>
                </TableFooter>
            </Table>
        </div>
    </div>
};


const useBuild = () => {
    const { toast } = useToast()

    // SSE 服务端推送
    async function streamNodeData(flow: FlowType, chatId: string) {
        let res = null
        // Step 1: Make a POST request to send the flow data and receive a unique session ID
        const _flow = { ...flow, id: flow.flow_id }
        const { flowId } = await postBuildInit({ flow: _flow, versionId: flow.id });
        // Step 2: Use the session ID to establish an SSE connection using EventSource
        let validationResults = [];
        let finished = false;
        let buildEnd = false
        const qstr = flow.id ? `?version_id=${flow.id}` : ''
        const apiUrl = `${__APP_ENV__.BASE_URL}/api/v1/build/stream/${flowId}${qstr}`;
        const eventSource = new EventSource(apiUrl);

        eventSource.onmessage = (event) => {
            // If the event is parseable, return
            if (!event.data) {
                return;
            }
            const parsedData = JSON.parse(event.data);
            // if the event is the end of the stream, close the connection
            if (parsedData.end_of_stream) {
                eventSource.close(); // 结束关闭链接
                buildEnd = true
                return;
            } else if (parsedData.log) {
                // If the event is a log, log it
                // setSuccessData({ title: parsedData.log });
            } else if (parsedData.input_keys) {
                res = parsedData
            } else {
                // setProgress(parsedData.progress);
                validationResults.push(parsedData.valid);
            }
        };

        eventSource.onerror = (error: any) => {
            console.error("EventSource failed:", error);
            eventSource.close();
            if (error.data) {
                const parsedData = JSON.parse(error.data);
                toast({
                    title: parsedData.error,
                    variant: 'error',
                    description: ''
                });
            }
        };
        // Step 3: Wait for the stream to finish
        while (!finished) {
            await new Promise((resolve) => setTimeout(resolve, 100));
            finished = buildEnd // validationResults.length === flow.data.nodes.length;
        }
        // Step 4: Return true if all nodes are valid, false otherwise
        if (validationResults.every((result) => result)) {
            return res
        }
    }

    // 延时器
    async function enforceMinimumLoadingTime(
        startTime: number,
        minimumLoadingTime: number
    ) {
        const elapsedTime = Date.now() - startTime;
        const remainingTime = minimumLoadingTime - elapsedTime;

        if (remainingTime > 0) {
            return new Promise((resolve) => setTimeout(resolve, remainingTime));
        }
    }

    async function handleBuild(flow: FlowStyleType) {
        try {
            const minimumLoadingTime = 200; // in milliseconds
            const startTime = Date.now();

            const res = await streamNodeData(flow, generateUUID(32));
            await enforceMinimumLoadingTime(startTime, minimumLoadingTime); // 至少等200ms, 再继续(强制最小load时间)
            return res
        } catch (error) {
            console.error("Error:", error);
        } finally {
        }
    }

    return handleBuild
}