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

// add QA
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
                    <DialogTitle>{t('similarQuestions')}</DialogTitle>
                </DialogHeader>
                <div className="flex flex-col gap-4 py-2 max-h-[36vh] overflow-y-auto">
                    <Table>
                        <TableRow>
                            <TableHead>{t('similarQuestionsPreview')}</TableHead>
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
                                                description: t('noSimilarQuestions')
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

const excelPreCheck = async (file, t) => {
    return new Promise((resolve) => {
        const ext = file.name.split('.').pop().toLowerCase();
        if (!['xlsx', 'xls'].includes(ext)) {
            return resolve({ valid: false, message: t('excelFileTypeError') });
        }

        const reader = new FileReader();

        reader.onload = (e) => {
            try {
                const data = new Uint8Array(e.target.result);
                const workbook = XLSX.read(data, { type: 'array' });
                const firstSheet = workbook.Sheets[workbook.SheetNames[0]];
                const jsonData = XLSX.utils.sheet_to_json(firstSheet, { header: 1 });

                if (jsonData.length === 0) {
                    resolve({ valid: false, message: t('excelFileEmpty') });
                    return;
                }

                const headers = jsonData[0].map(header => header?.toString().toLowerCase().trim());
                const requiredColumns = [t('question'), t('answer')];
                const missingColumns = requiredColumns.filter(
                    col => !headers.includes(col.toLowerCase())
                );

                if (missingColumns.length > 0) {
                    resolve({
                        valid: false,
                        message: t('missingRequiredColumns', { columns: missingColumns.join(', ') })
                    });
                } else {
                    resolve({ valid: true });
                }
            } catch (error) {
                resolve({ valid: false, message: t('excelParseError') });
            }
        };

        reader.onerror = () => {
            resolve({ valid: false, message: t('fileReadError') });
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

        if (isDataListEmpty) errors.push(t('emptyUploadData'));
        if (errors.length > 0) {
            return message({
                variant: 'warning',
                description: errors
            });
        }
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
        close();
        onChange();
    };
    const { id } = useParams();
    const handleFileUploadSuccess = async (name, url) => {
        const res = await captureAndAlertRequestErrorHoc(getQaFilePreview(id, {
            size: 10,
            url,
        }));
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
                    <DialogTitle>{t('importQA')}</DialogTitle>
                </DialogHeader>
                <div>
                    <div className="flex justify-between items-center">
                        <label htmlFor="dataSetName" className="bisheng-label">
                            <span className="text-red-500">*</span>{t('upFile')}
                        </label>
                        <div className="flex gap-2 items-center">
                            <Label>{t('exampleFile')}:</Label>
                            <Button variant="link" className="px-1" onClick={() => {
                                getQaFile('template').then(res => {
                                    const fileUrl = res.url;
                                    downloadFile(checkSassUrl(fileUrl), t('qaImportExampleFile'));
                                })
                            }}>
                                {t('qaImportExampleFile')}
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
                            preCheck={(file) => excelPreCheck(file, t)}
                        />
                        <p className="text-sm text-green-500 mt-2">{form.fileName}</p>
                    </div>
                </div>
                {!!dataList.length && <div>
                    <label htmlFor="dataSetName" className="bisheng-label">
                        {t('importPreview')}
                    </label>
                    <div className="flex flex-col gap-4 py-2 max-h-[36vh] overflow-y-auto">
                        <QaTable dataList={dataList} />
                    </div>
                </div>}
                <DialogFooter>
                    <DialogClose>
                        <Button variant="outline" className="px-11" type="button" onClick={close}>
                            {t('cancel')}
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