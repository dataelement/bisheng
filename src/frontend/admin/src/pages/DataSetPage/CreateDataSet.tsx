import KnowledgeSelect from "@/components/bs-comp/selectComponent/knowledge";
import { Button } from "@/components/bs-ui/button";
import { Dialog, DialogClose, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { Input } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/bs-ui/radio";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import SimpleUpload from "@/components/bs-ui/upload/simple";
import { createDatasetApi } from "@/controllers/API/finetune";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { downloadFile } from "@/util/utils";
import { forwardRef, useImperativeHandle, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

const DEFAULT_FORM = {
    dataSetName: '',
    importMethod: 'local',
    fileUrl: '',
    knowledgeLib: [],
    fileName: ''
};

const CreateDataSet = forwardRef(({ onChange }, ref) => {
    const { t } = useTranslation()
    const [open, setOpen] = useState(false);
    const [form, setForm] = useState({ ...DEFAULT_FORM });
    const [error, setError] = useState({
        dataSetName: false,
        fileUrl: false,
        knowledgeLib: false
    });
    const { message } = useToast();
    const idRef = useRef('');

    useImperativeHandle(ref, () => ({
        open() {
            idRef.current = '';
            setOpen(true);
            setForm({ ...DEFAULT_FORM });
            setError({
                dataSetName: false,
                fileUrl: false,
                knowledgeLib: false
            });
        }
    }));

    const handleInputChange = (e) => {
        const { name, value } = e.target;
        setForm((prevForm) => ({
            ...prevForm,
            [name]: value
        }));
    };

    const handleProviderChange = (value) => {
        setForm((prevForm) => ({
            ...prevForm,
            importMethod: value,
            fileUrl: '',
            knowledgeLib: [],
            fileName: ''
        }));
        setError((prevError) => ({
            ...prevError,
            fileUrl: false,
            knowledgeLib: false
        }));
    };

    const handleFileUploadSuccess = (name, url) => {
        setForm((prevForm) => ({
            ...prevForm,
            fileUrl: url,
            fileName: name
        }));
    };

    const handleKnowledgeLibChange = (value) => {
        setForm((prevForm) => ({
            ...prevForm,
            knowledgeLib: value
        }));
    };

    const handleSubmit = () => {
        const isDataSetNameEmpty = !form.dataSetName.trim();
        const isFileUrlEmpty = form.importMethod === 'local' && !form.fileUrl;
        const isKnowledgeLibEmpty = form.importMethod === 'qa' && form.knowledgeLib.length === 0;
        setError({
            dataSetName: isDataSetNameEmpty || form.dataSetName.length > 30,
            fileUrl: isFileUrlEmpty,
            knowledgeLib: isKnowledgeLibEmpty
        });

        const errors = [];
        if (isDataSetNameEmpty) errors.push(t('dataset.enterDataSetName'));
        if (form.dataSetName.length > 30) errors.push(t('dataset.maxDataSetNameLength'));
        if (isFileUrlEmpty) errors.push(t('dataset.uploadFile'));
        if (isKnowledgeLibEmpty) errors.push(t('dataset.selectKnowledgeLib'));
        if (errors.length > 0) {
            return message({
                variant: 'warning',
                description: errors
            });
        }
        setOpen(false);

        captureAndAlertRequestErrorHoc(createDatasetApi({
            name: form.dataSetName,
            files: form.fileUrl,
            qa_list: form.knowledgeLib.map(el => el.value)
        }).then(res => {
            message({
                variant: 'success',
                description: t('dataset.creationSuccess')
            });
            onChange();
        }));
    };

    return (
        <Dialog open={open} onOpenChange={setOpen}>
            <DialogContent className="sm:max-w-[625px]">
                <DialogHeader>
                    <DialogTitle>{t('dataset.createDataset')}</DialogTitle>
                </DialogHeader>
                <div className="flex flex-col gap-4 py-2">
                    <div>
                        <label htmlFor="dataSetName" className="bisheng-label">
                            <span className="text-red-500">*</span>{t('dataset.name')}
                        </label>
                        <Input
                            name="dataSetName"
                            className={`mt-2 ${error.dataSetName ? 'border-red-400' : ''}`}
                            value={form.dataSetName}
                            onChange={handleInputChange}
                        />
                    </div>
                    <div>
                        <label htmlFor="importMethod" className="bisheng-label">{t('dataset.importMethod')}</label>
                        <RadioGroup
                            defaultValue="local"
                            className="flex gap-6 mt-2"
                            onValueChange={handleProviderChange}
                        >
                            <div className="flex items-center space-x-2">
                                <RadioGroupItem value="local" id="method-local" />
                                <Label htmlFor="method-local">{t('dataset.localImport')}</Label>
                            </div>
                            <div className="flex items-center space-x-2">
                                <RadioGroupItem value="qa" id="method-qa" />
                                <Label htmlFor="method-qa">{t('dataset.importFromQa')}</Label>
                            </div>
                        </RadioGroup>
                    </div>
                    {form.importMethod === 'local' && (
                        <div>
                            <div className="flex justify-between items-center">
                                <label htmlFor="fileUpload" className="bisheng-label">
                                    <span className="text-red-500">*</span>{t('dataset.uploadFile')}
                                </label>
                                <div className="flex gap-2 items-center">
                                    <Label>{t('dataset.sampleFile')}:</Label>
                                    <Button variant="link" className="px-1" onClick={() => downloadFile(__APP_ENV__.BASE_URL + "/dataset.json", t('dataset.jsonSample'))}>
                                        {t('dataset.jsonSample')}
                                    </Button>
                                </div>
                            </div>
                            <SimpleUpload
                                filekey="file"
                                uploadUrl={__APP_ENV__.BASE_URL + '/api/v1/knowledge/upload'}
                                accept={['json']}
                                className={`${error.fileUrl ? 'border-red-400' : ''}`}
                                onSuccess={handleFileUploadSuccess}
                            />
                            <p className="text-sm text-green-500 mt-2">{form.fileName}</p>
                        </div>
                    )}
                    {form.importMethod === 'qa' && (
                        <div>
                            <label htmlFor="knowledgeLib" className="bisheng-label">
                                <span className="text-red-500">*</span>{t('dataset.selectQaKnowledgeLib')}
                            </label>
                            <KnowledgeSelect
                                type="qa"
                                multiple
                                value={form.knowledgeLib}
                                onChange={handleKnowledgeLibChange}
                                className={`${error.knowledgeLib ? 'border-red-400' : ''}`}
                            />
                        </div>
                    )}
                </div>
                <DialogFooter>
                    <DialogClose>
                        <Button variant="outline" className="px-11" type="button" onClick={() => setOpen(false)}>{t('cancel')}</Button>
                    </DialogClose>
                    <Button type="submit" className="px-11" onClick={handleSubmit}>{t('confirm')}</Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
});

export default CreateDataSet;
