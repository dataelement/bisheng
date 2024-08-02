import KnowledgeSelect from "@/components/bs-comp/selectComponent/knowledge";
import { Button } from "@/components/bs-ui/button";
import { Dialog, DialogClose, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { Input } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/bs-ui/radio";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import SimpleUpload from "@/components/bs-ui/upload/simple";
import { downloadFile } from "@/util/utils";
import { forwardRef, useImperativeHandle, useRef, useState } from "react";

const DEFAULT_FORM = {
    dataSetName: '',
    importMethod: 'local',
    fileUrl: '',
    knowledgeLib: [],
    fileName: ''
};

const CreateDataSet = forwardRef(({ onChange }, ref) => {
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
            dataSetName: isDataSetNameEmpty,
            fileUrl: isFileUrlEmpty,
            knowledgeLib: isKnowledgeLibEmpty
        });

        const errors = []
        if (isDataSetNameEmpty) errors.push('请填写数据集名称')
        if (isFileUrlEmpty) errors.push('请填上传文件')
        if (isKnowledgeLibEmpty) errors.push('请填选择知识库')
        if (errors.length > 0) {
            return message({
                variant: 'warning',
                description: errors
            })
        }
        setOpen(false);

        console.log('form :>> ', form);
        // 调用接口，假设此处成功
        setTimeout(() => {
            message({
                variant: 'success',
                description: '数据集创建成功'
            });
            onChange()
        }, 500);
    };

    return (
        <Dialog open={open} onOpenChange={setOpen}>
            <DialogContent className="sm:max-w-[625px]">
                <DialogHeader>
                    <DialogTitle>创建数据集</DialogTitle>
                </DialogHeader>
                <div className="flex flex-col gap-4 py-2">
                    <div>
                        <label htmlFor="dataSetName" className="bisheng-label">
                            <span className="text-red-500">*</span>数据集名称
                        </label>
                        <Input
                            name="dataSetName"
                            className={`mt-2 ${error.dataSetName ? 'border-red-400' : ''}`}
                            value={form.dataSetName}
                            onChange={handleInputChange}
                        />
                    </div>
                    <div>
                        <label htmlFor="importMethod" className="bisheng-label">导入方式</label>
                        <RadioGroup
                            defaultValue="local"
                            className="flex gap-6 mt-2"
                            onValueChange={handleProviderChange}
                        >
                            <div className="flex items-center space-x-2">
                                <RadioGroupItem value="local" id="method-local" />
                                <Label htmlFor="method-local">本地导入</Label>
                            </div>
                            <div className="flex items-center space-x-2">
                                <RadioGroupItem value="qa" id="method-qa" />
                                <Label htmlFor="method-qa">从QA知识库导入</Label>
                            </div>
                        </RadioGroup>
                    </div>
                    {form.importMethod === 'local' && (
                        <div>
                            <div className="flex justify-between items-center">
                                <label htmlFor="fileUpload" className="bisheng-label">
                                    <span className="text-red-500">*</span>上传文件
                                </label>
                                <div className="flex gap-2 items-center">
                                    <Label>示例文件：</Label>
                                    <Button variant="link" className="px-1" onClick={() => downloadFile(__APP_ENV__.BASE_URL + "/dataset.csv", 'CSV格式示例.csv')}>CSV格式示例</Button>
                                    <Button variant="link" className="px-1" onClick={() => downloadFile(__APP_ENV__.BASE_URL + "/dataset.json", 'json格式示例.json')}>json格式示例</Button>
                                </div>
                            </div>
                            <SimpleUpload
                                filekey='file'
                                uploadUrl={__APP_ENV__.BASE_URL + '/api/v1/knowledge/upload'}
                                accept={['csv', 'json']}
                                className={`${error.fileUrl ? 'border-red-400' : ''}`}
                                onSuccess={handleFileUploadSuccess}
                            />
                            <p className="text-sm text-green-500 mt-2">{form.fileName}</p>
                        </div>
                    )}
                    {form.importMethod === 'qa' && (
                        <div>
                            <label htmlFor="knowledgeLib" className="bisheng-label">
                                <span className="text-red-500">*</span>选择QA知识库
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
                        <Button variant="outline" className="px-11" type="button" onClick={() => setOpen(false)}>取消</Button>
                    </DialogClose>
                    <Button type="submit" className="px-11" onClick={handleSubmit}>确认</Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
});

export default CreateDataSet;
