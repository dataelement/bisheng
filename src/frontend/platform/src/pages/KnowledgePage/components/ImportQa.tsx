import { checkSassUrl } from "@/components/bs-comp/FileView";
import { Button, LoadButton } from "@/components/bs-ui/button";
import { Dialog, DialogClose, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { Label } from "@/components/bs-ui/label";
import { Table, TableBody, TableCell, TableHead, TableRow } from "@/components/bs-ui/table";
import { message } from "@/components/bs-ui/toast/use-toast";
import SimpleUpload from "@/components/bs-ui/upload/simple";
import { getQaFile, getQaFilePreview, postImportQaFile } from "@/controllers/API";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { downloadFile } from "@/util/utils";
import { generateUUID } from "@/utils";
import { forwardRef, useImperativeHandle, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";
import * as XLSX from 'xlsx';

// 添加&编辑qa
const SimilarityProblemModal = forwardRef(function ({ questions }, ref) {
    const { t } = useTranslation('knowledge');
    const [open, setOpen] = useState(false);

    const idRef = useRef('');
    const sourceRef = useRef('');
    useImperativeHandle(ref, () => ({
        open() {
            setOpen(true);
        },
    }));

    const close = () => {
        setOpen(false);
    };
    return (
        <Dialog open={open} onOpenChange={(bln) => bln ? setOpen(bln) : close()}>
            <DialogContent className="sm:max-w-[625px]">
                <DialogHeader>
                    <DialogTitle>相似问题</DialogTitle>
                </DialogHeader>
                <div className="flex flex-col gap-4 py-2 max-h-[36vh] overflow-y-auto">
                    <Table>
                        <TableRow>
                            <TableHead>相似问题（仅显示前十条）</TableHead>
                        </TableRow>
                        <TableBody>
                            {(questions || []).slice(0, 10).map((el, index) => {
                                return (
                                    <TableRow key={index}>
                                        <TableCell className="font-medium">
                                            {el}
                                        </TableCell>
                                    </TableRow>
                                )
                            })
                            }
                        </TableBody>
                    </Table>
                </div>
                <DialogFooter>
                    <DialogClose>
                        <LoadButton type="submit" className="px-11">
                            {t('confirm')}
                        </LoadButton>
                    </DialogClose>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
});

function QaTable({ dataList }) {
    const { t } = useTranslation('knowledge');
    const similarityQuestions = useRef(null);
    const [questions, setQuestions] = useState<string[]>([]);
    return (
        <div>
            <Table>
                <TableRow>
                    <TableHead>{t('question')}</TableHead>
                    <TableHead>{t('answer')}</TableHead>
                    <TableHead className="">{t('similarQuestions')}</TableHead>
                </TableRow>
                <TableBody>
                    {dataList.map(el => {
                        const questions = el.questions.filter(item => !!item);
                        const mainQuestion = questions.shift() || '';
                        const answers = JSON.parse(el.answers);
                        const answer = answers[0] || '';
                        return (
                            <TableRow key={generateUUID(4)}>
                                <TableCell className="font-medium">
                                    {mainQuestion}
                                </TableCell>
                                <TableCell className="font-medium">
                                    {answer}
                                </TableCell>
                                <TableCell className="font-medium cursor-pointer text-primary">
                                    <Button variant="link" className="px-1" onClick={() => {
                                        if (!questions.length) {
                                            return message({
                                                variant: 'warning',
                                                description: '暂无相似问题'
                                            });
                                        }
                                        setQuestions(questions);
                                        //打开相似问题预览窗口
                                        similarityQuestions.current.open();
                                    }}>
                                        {t('view')}
                                    </Button>
                                </TableCell>
                            </TableRow>
                        )
                    })
                    }
                    <SimilarityProblemModal ref={similarityQuestions} questions={questions} />
                </TableBody>
            </Table>
        </div>
    );
}

// Excel校验函数
const excelPreCheck = async (file) => {
    return new Promise((resolve) => {
        // 检查是否是Excel文件
        const ext = file.name.split('.').pop().toLowerCase();
        if (!['xlsx', 'xls'].includes(ext)) {
            return { valid: false, message: '请上传xlsx、xls类型的文件' }; // 非Excel文件跳过校验
        }

        const reader = new FileReader();

        reader.onload = (e) => {
            try {
                const data = new Uint8Array(e.target.result);
                const workbook = XLSX.read(data, { type: 'array' });
                const firstSheet = workbook.Sheets[workbook.SheetNames[0]];
                const jsonData = XLSX.utils.sheet_to_json(firstSheet, { header: 1 });

                if (jsonData.length === 0) {
                    resolve({ valid: false, message: 'Excel文件为空' });
                    return;
                }

                const headers = jsonData[0].map(header => header?.toString().toLowerCase().trim());
                const requiredColumns = ['问题', '答案'];
                const missingColumns = requiredColumns.filter(
                    col => !headers.includes(col.toLowerCase())
                );

                if (missingColumns.length > 0) {
                    resolve({
                        valid: false,
                        message: `缺少必要列: ${missingColumns.join(', ')}`
                    });
                } else {
                    resolve({ valid: true });
                }
            } catch (error) {
                resolve({ valid: false, message: 'Excel文件解析失败' });
            }
        };

        reader.onerror = () => {
            resolve({ valid: false, message: '文件读取失败' });
        };

        reader.readAsArrayBuffer(file);
    });
};

// 导入Qa
export const ImportQa = forwardRef(function ({ knowlageId, onChange }: any, ref) {
    const { t } = useTranslation('knowledge');
    const [open, setOpen] = useState(false);
    const [saveLoad, setSaveLoad] = useState(false);
    const [dataList, setDataList] = useState([]);
    const [form, setForm] = useState({
        fileUrl: '',
        fileName: '',
    });
    const [error, setError] = useState({
        fileUrl: false,
    });

    useImperativeHandle(ref, () => ({
        open() {
            setOpen(true);
            setForm({
                fileUrl: '',
                fileName: '',
            });
            setError({
                fileUrl: false,
            });
            setDataList([]);
        }
    }));

    const close = () => {
        setOpen(false);
        setError({
            fileUrl: false,
        });
    };

    const handleSubmit = async () => {
        const isDataListEmpty = !dataList.length;
        const errors = [];
        setError({
            fileUrl: isDataListEmpty,
        });

        if (isDataListEmpty) errors.push('待上传问题为空，请检查');
        if (errors.length > 0) {
            return message({
                variant: 'warning',
                description: errors
            });
        }
        setSaveLoad(true);
        //提交
        const res = await captureAndAlertRequestErrorHoc(postImportQaFile(id, {
            url: form.fileUrl
        }));
        const errorLines = res.errors[0];
        console.log('errors', errorLines);
        if (errorLines.length) {
            message({ variant: 'warning', description: t('errorMsg', { value: errorLines.length }) });
        } else {
            message({ variant: 'success', description: t('successMsg') });
        }
        setSaveLoad(false);
        close();
        onChange();
    };
    const { id } = useParams();
    const handleFileUploadSuccess = async (name, url) => {
        // 发送请求进行预览
        setSaveLoad(true);
        const res = await captureAndAlertRequestErrorHoc(getQaFilePreview(id, {
            // 最多预览10条
            size: 10,
            url,
        }));
        setSaveLoad(false);
        const { result } = res;
        setDataList(result);
        setForm({
            fileUrl: url,
            fileName: name
        });
    };

    return (
        <Dialog open={open} onOpenChange={(bln) => bln ? setOpen(bln) : close()}>
            <DialogContent className="sm:max-w-[825px]">
                <DialogHeader>
                    <DialogTitle>导入 QA</DialogTitle>
                </DialogHeader>
                <div>
                    <div className="flex justify-between items-center">
                        <label htmlFor="dataSetName" className="bisheng-label">
                            <span className="text-red-500">*</span>请上传文件
                        </label>
                        <div className="flex gap-2 items-center">
                            <Label>示例文件:</Label>
                            <Button variant="link" className="px-1" onClick={() => {
                                getQaFile('template').then(res => {
                                    const fileUrl = res.url;
                                    downloadFile(checkSassUrl(fileUrl), 'QA导入格式示例.xlsx');
                                })
                            }}>
                                QA导入格式示例.xlsx
                            </Button>
                        </div>
                    </div>
                    <div className="flex flex-col gap-4 py-2">
                        <SimpleUpload
                            filekey="file"
                            uploadUrl={'/api/v1/knowledge/upload'}
                            accept={['xls', 'xlsx']}
                            className={`${error.fileUrl ? 'border-red-400' : ''}`}
                            onSuccess={handleFileUploadSuccess}
                            preCheck={excelPreCheck}
                        />
                        <p className="text-sm text-green-500 mt-2">{form.fileName}</p>
                    </div>
                </div>
                {!!dataList.length && <div>
                    <label htmlFor="dataSetName" className="bisheng-label">
                        导入预览（仅显示前十条）
                    </label>
                    <div className="flex flex-col gap-4 py-2 max-h-[36vh] overflow-y-auto">
                        <QaTable dataList={dataList} />
                    </div>
                </div>}
                <DialogFooter>
                    <DialogClose>
                        <Button variant="outline" className="px-11" type="button" onClick={close}>
                            取消
                        </Button>
                    </DialogClose>
                    <LoadButton loading={saveLoad} type="submit" className="px-11" onClick={handleSubmit}>
                        {t('submit')}
                    </LoadButton>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
})