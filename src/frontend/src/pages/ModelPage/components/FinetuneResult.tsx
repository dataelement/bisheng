import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../../components/bs-ui/card";
import { getTaskInfoApi } from "../../../controllers/API/finetune";
import { TaskStatus } from "./FinetuneDetail";

export default function FinetuneResult({ id, training, isStop, failed, onChange }) {
    const { t } = useTranslation('model')
    const timerRef = useRef(null)

    const [logs, setLogs] = useState(null)
    const [report, setReport] = useState(null)
    const [loss, setLoss] = useState([])

    const [count, setCount] = useState(0)
    useEffect(() => {
        if (!training) return loadData()

        clearTimeout(timerRef.current)
        timerRef.current = setTimeout(() => {
            console.log('2s');
            loadData(true)

            setCount(count + 1)
        }, 2000)

        return () => clearTimeout(timerRef.current)
    }, [id, training, count])

    const loadData = (loop?) => {
        getTaskInfoApi(id).then((data) => {
            const { log, report, loss_data, finetune } = data
            setLogs(log)
            setReport(report)
            setLoss(loss_data)
            // 状态变更停止轮训
            loop && finetune.status !== TaskStatus.TRAINING_IN_PROGRESS && onChange(finetune.status)
        })
    }

    const processKeys = ['bleu-4', 'rouge-1', 'rouge-2', 'rouge-l']

    return <div>
        <div className="border-b pb-4">
            <div className="flex gap-4 mt-4">
                <small className="text-sm font-medium leading-none text-gray-500">{t('finetune.evaluationReport')}</small>
                {(failed || isStop) && <small className="text-sm font-medium leading-none text-gray-700">--</small>}
            </div>

            {/* cards */}
            {
                // 失败 中止不展示 cards
                !failed && !isStop && report && <div className="flex gap-4 mt-4">
                    {
                        processKeys.map(key => <Card className="flex-row w-[25%]" key={key}>
                            <CardHeader>
                                <CardTitle>{key}</CardTitle>
                                <CardDescription>{training ? '--' : report[`predict_${key}`]?.toFixed(2) || '--'}%</CardDescription>
                            </CardHeader>
                            <CardContent className="mt-4">
                                <div className="radial-progress bg-gray-200 dark:bg-gray-950" style={{ "--value": training ? 0 : report[`predict_${key}`], "--size": "1.4rem", }} role="progressbar"></div>
                            </CardContent>
                        </Card>)
                    }
                </div>
            }
            {/* chart */}
            {
                !failed && !isStop && report && <div className="mt-4">
                    <ResponsiveContainer className="border rounded-md" width="100%" height={280}>
                        <AreaChart data={loss}
                            margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
                            <defs>
                                <linearGradient id="colorUv" x1="0" y1="0" x2="0" y2="1">
                                    <stop offset="5%" stopColor="#4e83fd" stopOpacity={0.4} />
                                    <stop offset="95%" stopColor="#4e83fd" stopOpacity={0} />
                                </linearGradient>
                            </defs>
                            <XAxis dataKey="step" />
                            <YAxis />
                            <CartesianGrid vertical={false} />
                            <Tooltip />
                            <Area type="monotone" dataKey="loss" stroke="#8884d8" fillOpacity={1} fill="url(#colorUv)" />
                        </AreaChart>
                    </ResponsiveContainer>
                </div>
            }
        </div>
        {/* log */}
        <div className="pb-4">
            <div className="flex gap-4 mt-4">
                <small className="text-sm font-medium leading-none text-gray-500">{t('finetune.trainingLogs')}</small>
            </div>
            <div className="mt-4 rounded-md bg-gray-100 dark:bg-gray-800 p-2 overflow-auto max-w-full h-[400px]">
                <pre className="text-gray-500 text-sm max-w-[500px]">{logs}</pre>
            </div>
        </div>
    </div>
};
