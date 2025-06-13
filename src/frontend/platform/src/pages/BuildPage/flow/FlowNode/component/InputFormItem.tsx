import { Button } from "@/components/bs-ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { Input } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { Switch } from "@/components/bs-ui/switch";
import { QuestionTooltip } from "@/components/bs-ui/tooltip";
import { isVarInFlow } from "@/util/flowUtils";
import { cloneDeep } from "lodash-es";
import { ChevronsDown, CloudUpload, Type } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next"; // 引入国际化
import useFlowStore from "../../flowStore";
import DragOptions from "./DragOptions";
import FileTypeSelect from "./FileTypeSelect";
import InputItem from "./InputItem";
import VarInput from "./VarInput";

const enum FormType {
    Text = "text",
    Select = "select",
    File = "file",
}

const names = {
    [FormType.Text]: "text_input",
    [FormType.Select]: "category",
    [FormType.File]: "file",
}

function Form({ nodeId, nodeData, initialData, onSubmit, onCancel, existingOptions }) {
    const { t } = useTranslation('flow');
    const namePlaceholders = {
        [FormType.Text]: t("nameExample"), // 例如“姓名”
        [FormType.Select]: t("categoryExample"), // 例如“保险类别”
        [FormType.File]: t("uploadExample"), // 例如“请上传去年财报”
    };

    const [formData, setFormData] = useState({
        formType: FormType.Text,
        displayName: "",
        variableName: "",
        filecontent: '',
        filepath: '',
        fileType: 'all',
        fileTypes: ['file', 'image', 'audio'],
        fileContentSize: 15000,
        imageFile: '',
        audioFile: '',
        isMultiple: true, // default value for multiple file upload
        isRequired: true,
        allowMultiple: false,  // Allow multiple file uploads
        options: [],  // Options for Select input
    });
    const [errors, setErrors] = useState<any>({});
    const editRef = useRef(false); // 编辑状态
    const oldFormTypeRef = useRef('')
    const displayNameRef = useRef({ // 记忆变量名
        [FormType.Text]: '',
        [FormType.Select]: '',
        [FormType.File]: '',
    });


    const oldVarNameRef = useRef("");
    const oldcontentNameRef = useRef("");
    const oldPathNameRef = useRef("");
    const oldImageFileRef = useRef("");
    const oldAudioFileRef = useRef("");
    useEffect(() => {
        editRef.current = false
        if (initialData) {
            const {
                type: formType,
                value: displayName,
                key: variableName,
                required: isRequired,
                multiple: allowMultiple,
                file_content: filecontent,
                file_type: fileType,
                file_types: fileTypes,
                file_path: filepath,
                file_content_size: fileContentSize,
                image_file: imageFile,
                audio_file: audioFile,
                options = [] } = initialData;
            setFormData({
                formType,
                displayName,
                variableName,
                isRequired,
                allowMultiple,
                options,
                filecontent,
                fileType,
                fileTypes,
                filepath,
                fileContentSize,
                imageFile,
                audioFile,
                isMultiple: allowMultiple
            });

            editRef.current = true
            oldFormTypeRef.current = formType
            oldVarNameRef.current = variableName;
            oldcontentNameRef.current = filecontent;
            oldPathNameRef.current = filepath;
            oldImageFileRef.current = imageFile;
            oldAudioFileRef.current = audioFile;
        }
    }, [initialData]);

    // 变量重命名
    useEffect(() => {
        if (initialData) return
        // 初始化变量名
        let initialVarName = names[formData.formType];
        let initialFileContent = 'file_content'
        let initialFilePath = 'file_path'
        let initialFileImage = 'image_file'
        let initialFileAudio = 'audio_file'
        let counter = 1;
        let initialFileContentCounter = 1;
        let initialFilePathCounter = 1;
        let initialFileImageCounter = 1
        let initialFileAudioCounter = 1
        while (existingOptions?.some(opt => opt.key === initialVarName)) {
            counter += 1;
            initialVarName = `${names[formData.formType]}${counter}`;
        }
        const fileOtions = existingOptions?.filter(opt => opt.type === FormType.File)
        while (fileOtions?.some(opt => opt.file_content === initialFileContent)) {
            initialFileContentCounter += 1;
            initialFileContent = `file_content${initialFileContentCounter}`;
        }
        while (fileOtions?.some(opt => opt.file_path === initialFilePath)) {
            initialFilePathCounter += 1;
            initialFilePath = `file_path${initialFilePathCounter}`;
        }
        while (fileOtions?.some(opt => opt.image_file === initialFileImage)) {
            initialFileImageCounter += 1;
            initialFileImage = `image_file${initialFileImageCounter}`;
        }
        while (fileOtions?.some(opt => opt.audio_file === initialFileAudio)) {
            initialFileAudioCounter += 1;
            initialFileAudio = `audio_file${initialFileAudioCounter}`;
        }
        // 变量重命名
        // existingOptions.
        setFormData((prevData) => ({
            ...prevData,
            variableName: initialVarName,
            filecontent: initialFileContent,
            filepath: initialFilePath,
            imageFile: initialFileImage,
            audioFile: initialFileAudio
        }));
    }, [initialData, formData.formType])

    const validateForm = () => {
        const newErrors: any = {};

        if (!formData.displayName.trim()) {
            newErrors.displayName = t("displayNameRequired");
        } else if (formData.displayName.length > 50) {
            newErrors.displayName = t("displayNameTooLong");
        }

        if (!formData.variableName.trim()) {
            newErrors.variableName = t("variableNameRequired");
        } else if (formData.variableName.length > 50) {
            newErrors.variableName = t("variableNameTooLong");
        } else if (!/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(formData.variableName)) {
            newErrors.variableName = t("variableNameInvalid");
        } else if (
            existingOptions?.some(opt => opt.key === formData.variableName) &&
            formData.variableName !== oldVarNameRef.current
        ) {
            newErrors.variableName = t("variableNameExists");
        }

        if (formData.formType === FormType.Select && !formData.options.length) {
            newErrors.options = t("optionsRequired");
        }

        // Validation for file upload variables (if multiple files are allowed)
        if (formData.formType === FormType.File) {
            // Validate file content variable name
            if (!formData.filecontent.trim()) {
                newErrors.filecontent = t("variableNameRequired");
            } else if (!/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(formData.filecontent)) {
                newErrors.filecontent = t("variableNameInvalid");
            } else if (formData.filecontent.length > 50) {
                newErrors.filecontent = t("variableNameTooLong");
            } else if (
                existingOptions?.some(opt => opt.type === 'file'
                    && opt.file_content === formData.filecontent)
                && formData.filecontent !== oldcontentNameRef.current
            ) {
                newErrors.filecontent = t("variableNameExists");
            }

            // Validate file path variable name
            if (!formData.filepath.trim()) {
                newErrors.filepath = t("variableNameRequired");
            } else if (!/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(formData.filepath)) {
                newErrors.filepath = t("variableNameInvalid");
            } else if (formData.filepath.length > 50) {
                newErrors.filepath = t("variableNameTooLong");
            } else if (
                existingOptions?.some(opt => opt.type === 'file'
                    && opt.file_path === formData.filepath)
                && formData.filepath !== oldPathNameRef.current
            ) {
                newErrors.filepath = t("variableNameExists");
            }
            if (formData.fileTypes.includes('image')) {
                const _error = validateFileVariableName(formData.imageFile, existingOptions, 'image');
                if (_error) {
                    newErrors.imageFile = _error
                }
            }
            if (formData.fileTypes.includes('audio')) {
                const _error = validateFileVariableName(formData.imageFile, existingOptions, 'audio');
                if (_error) {
                    newErrors.audioFile = _error
                }
            }
        }


        setErrors(newErrors);
        return Object.keys(newErrors).length === 0;
    };

    const validateFileVariableName = (varName, existingOptions, fileType: 'image' | 'audio') => {
        const errors = [];

        // 1. 非空检查
        if (!varName || !varName.trim()) {
            return '变量名称不可为空'
        }

        // 2. 不能以数字开头
        if (/^\d/.test(varName)) {
            return '变量名不能以数字开头';
        }

        // 3. 只能包含英文字符、数字和下划线
        if (!/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(varName)) {
            return '变量名称只能包含英文字符、数字和下划线';
        }

        // 4. 长度不超过50
        if (varName.length > 50) {
            return '变量名称不能超过50个字符';
        }
        
        // 5. 不能重复
        if (fileType === 'image') {
            if (existingOptions?.some(opt => opt.type === 'file'
                && opt.image_file === formData.imageFile)
                && formData.imageFile !== oldImageFileRef.current) {
                return '变量名已存在';
            }
        } else if (fileType === 'audio') {
            if (existingOptions?.some(opt => opt.type === 'file'
                && opt.audio_file === formData.audioFile)
                && formData.audioFile !== oldAudioFileRef.current) {
                return '变量名已存在';
            }
        }

        return '';
    };

    const handleFormSubmit = (e) => {
        e.preventDefault();
        if (validateForm()) {
            onSubmit(formData);
        }
    };

    const updateOptions = (options) => {
        setFormData((prevData) => ({
            ...prevData,
            options,
        }));
    };

    // if the form type hasn't changed, it keeps the variable name as it was. Otherwise, it generates a new unique variable name.
    const handleChangeFormType = (formType) => {
        displayNameRef.current[formData.formType] = formData.displayName;
        const displayName = displayNameRef.current[formType] || '';
        setFormData({ ...formData, displayName, formType })
        setErrors({});
        if (editRef.current) {
            if (oldFormTypeRef.current === formType) {
                setFormData({ ...formData, formType, variableName: oldVarNameRef.current, displayName })
            } else {
                let counter = 1;
                let initialVarName = names[formType];
                while (existingOptions?.some(opt => opt.key === initialVarName)) {
                    counter += 1;
                    initialVarName = `${names[formType]}${counter}`;
                }
                setFormData({ ...formData, formType, variableName: initialVarName, displayName })
            }
        }
    }

    // var check
    const checkVarFuncRef = useRef(null);
    useEffect(() => {
        if (initialData && checkVarFuncRef.current && formData.formType === FormType.Text) {
            checkVarFuncRef.current();
        }
    }, [formData.formType, initialData])

    // text form
    const InputForm = <div className="space-y-4">
        <div>
            <Label className="flex items-center bisheng-label">
                {t("displayName")}
                <QuestionTooltip content={t("displayNameTooltip")} />
            </Label>
            {/* <Input
                className={`mt-2 ${errors.displayName ? "border-red-500" : ""}`}
                id="displayName"
                placeholder={namePlaceholders[formData.formType]}
                value={formData.displayName}
                onChange={(e) => setFormData({ ...formData, displayName: e.target.value })}
            /> */}
            <VarInput
                mini
                key={formData.variableName}
                label={''}
                itemKey={''}
                nodeId={nodeId}
                flowNode={nodeData}
                value={formData.displayName}
                placeholder={namePlaceholders[formData.formType]}
                onChange={(val) => setFormData({ ...formData, displayName: val })}
                onVarEvent={(func) => checkVarFuncRef.current = func}
            >
            </VarInput>
            {errors.displayName && <p className="text-red-500 text-sm">{errors.displayName}</p>}
        </div>
        <div>
            <Label className="flex items-center bisheng-label">
                {t("variableName")}
                <QuestionTooltip content={t("variableNameTooltip")} />
            </Label>
            <Input
                className={`mt-2 ${errors.variableName ? "border-red-500" : ""}`}
                id="variableName"
                placeholder={t("enterVariableName")}
                value={formData.variableName}
                onChange={(e) => setFormData({ ...formData, variableName: e.target.value })}
            />
            {errors.variableName && <p className="text-red-500 text-sm">{errors.variableName}</p>}
        </div>
        <div className="flex items-center space-x-2">
            <Label className="bisheng-label">{t('isRequired')}</Label>
            <Switch
                checked={formData.isRequired}
                onCheckedChange={(checked) => setFormData({ ...formData, isRequired: checked })}
            />
        </div>
    </div>
    // select from 
    const SelectForm = <div className="space-y-4">
        <div>
            <Label className="flex items-center bisheng-label">
                {t("displayName")}
                <QuestionTooltip content={t("displayNameTooltip")} />
            </Label>
            <Input
                className={`mt-2 ${errors.displayName ? "border-red-500" : ""}`}
                id="displayName"
                placeholder={namePlaceholders[formData.formType]}
                value={formData.displayName}
                onChange={(e) => setFormData({ ...formData, displayName: e.target.value })}
            />
            {errors.displayName && <p className="text-red-500 text-sm">{errors.displayName}</p>}
        </div>
        <div>
            <Label className="flex items-center bisheng-label">
                {t("variableName")}
                <QuestionTooltip content={t("variableNameTooltip")} />
            </Label>
            <Input
                className={`mt-2 ${errors.variableName ? "border-red-500" : ""}`}
                id="variableName"
                placeholder={t("enterVariableName")}
                value={formData.variableName}
                onChange={(e) => setFormData({ ...formData, variableName: e.target.value })}
            />
            {errors.variableName && <p className="text-red-500 text-sm">{errors.variableName}</p>}
        </div>
        <div>
            <Label className="bisheng-label">{t("options")}</Label>
            <DragOptions edit scroll options={formData.options} onChange={updateOptions} />
            {errors.options && <p className="text-red-500 text-sm">{errors.options}</p>}
        </div>
        <div className="flex items-center space-x-2">
            <Label className="bisheng-label">允许多选</Label>
            <Switch
                checked={formData.allowMultiple}
                onCheckedChange={(checked) => setFormData({ ...formData, allowMultiple: checked })}
            />
        </div>
        <div className="flex items-center space-x-2">
            <Label className="bisheng-label">{t('isRequired')}</Label>
            <Switch
                checked={formData.isRequired}
                onCheckedChange={(checked) => setFormData({ ...formData, isRequired: checked })}
            />
        </div>
    </div>
    // file form 
    const FileForm = <div className="space-y-4">
        <div>
            <Label className="flex items-center bisheng-label">
                {t("displayName")}
                <QuestionTooltip content={t("displayNameTooltip")} />
            </Label>
            <Input
                className={`mt-2 ${errors.displayName ? "border-red-500" : ""}`}
                id="displayName"
                placeholder={namePlaceholders[formData.formType]}
                value={formData.displayName}
                onChange={(e) => setFormData({ ...formData, displayName: e.target.value })}
            />
            {errors.displayName && <p className="text-red-500 text-sm">{errors.displayName}</p>}
        </div>

        <div className="flex items-center space-x-2">
            <Label className="bisheng-label">{t('isRequired')}</Label>
            <Switch
                checked={formData.isRequired}
                onCheckedChange={(checked) => setFormData({ ...formData, isRequired: checked })}
            />
        </div>

        <div className="flex items-center space-x-2">
            <Label className="bisheng-label">允许上传多个文件</Label>
            <Switch
                checked={formData.isMultiple}
                onCheckedChange={(checked) => setFormData({ ...formData, isMultiple: checked })}
            />
        </div>
        <FileTypeSelect data={{
            label: "上传文件类型",
            value: formData.fileTypes,
        }} onChange={(fileTypes) => setFormData({ ...formData, fileTypes })} />
        <div>
            <Label className="flex items-center bisheng-label">
                临时知识库名称
                <QuestionTooltip content={'文件将会上传到以此命名的临时知识库中，可在文档知识库问答、助手等节点中使用'} />
            </Label>
            <Input
                className={`mt-2 ${errors.variableName ? "border-red-500" : ""}`}
                id="variableName"
                placeholder={t("enterVariableName")}
                value={formData.variableName}
                onChange={(e) => setFormData({ ...formData, variableName: e.target.value })}
            />
            {errors.variableName && <p className="text-red-500 text-sm">{errors.variableName}</p>}
        </div>

        <div>
            <Label className="flex items-center bisheng-label">
                文件内容变量名称
                <QuestionTooltip content={'文件解析结果全文将会存储在此变量中，使用时请注意可能会超出模型上下文长度'} />
            </Label>
            <Input
                className={`mt-2 ${errors.filecontent ? "border-red-500" : ""}`}
                id="filecontent"
                placeholder={t("enterVariableName")}
                value={formData.filecontent}
                onChange={(e) => setFormData({ ...formData, filecontent: e.target.value })}
            />
            {errors.filecontent && <p className="text-red-500 text-sm">{errors.filecontent}</p>}
        </div>
        <InputItem
            type='number'
            char
            linefeed
            data={
                {
                    min: 0,
                    label: "文件内容长度上限",
                    value: formData.fileContentSize,
                }
            }
            onChange={(fileContentSize) => setFormData({ ...formData, fileContentSize })}
        />
        <div>
            <Label className="flex items-center bisheng-label">
                文件路径变量名称
                <QuestionTooltip content={'文件路径将会存储在此变量中，后续可在代码节点中使用'} />
            </Label>
            <Input
                className={`mt-2 ${errors.filepath ? "border-red-500" : ""}`}
                id="filepath"
                placeholder={t("enterVariableName")}
                value={formData.filepath}
                onChange={(e) => setFormData({ ...formData, filepath: e.target.value })}
            />
            {errors.filepath && <p className="text-red-500 text-sm">{errors.filepath}</p>}
        </div>
        {formData.fileTypes.includes('image') && <div>
            <Label className="flex items-center bisheng-label">
                上传图片文件
                <QuestionTooltip content={'提取上传文件中的图片文件，当助手或大模型节点使用多模态大模型时，可传入此图片。'} />
            </Label>
            <Input
                className={`mt-2 ${errors.imageFile ? "border-red-500" : ""}`}
                id="imageFile"
                placeholder={t("enterVariableName")}
                value={formData.imageFile}
                onChange={(e) => setFormData({ ...formData, imageFile: e.target.value })}
            />
            {errors.imageFile && <p className="text-red-500 text-sm">{errors.imageFile}</p>}
        </div>}
        {formData.fileTypes.includes('audio') && <div>
            <Label className="flex items-center bisheng-label">
                上传音频文件
                <QuestionTooltip content={'提取上传文件中的音频文件，当使用音频转文字时，可传入此音频。'} />
            </Label>
            
            <Input
                className={`mt-2 ${errors.audioFile ? "border-red-500" : ""}`}
                id="audioFile"
                placeholder={t("enterVariableName")}
                value={formData.audioFile}
                onChange={(e) => setFormData({ ...formData, audioFile: e.target.value })}
            />
            {errors.audioFile && <p className="text-red-500 text-sm">{errors.audioFile}</p>}
        </div>}
    </div>;

    return (
        <form onSubmit={handleFormSubmit} className="space-y-4">
            <div>
                <Label className="bisheng-label">{t("formType")}</Label>
                <div className="flex gap-4 justify-between mx-6 mt-2">
                    <Button
                        className={`flex flex-col h-18 w-28 ${formData.formType === FormType.Text ? "border-primary/40 bg-[#DFE9FD] text-primary" : ""}`}
                        type="button"
                        variant="outline"
                        onClick={() => handleChangeFormType(FormType.Text)}
                    >
                        <Type size={18} />
                        {t("textInput")}
                    </Button>
                    <Button
                        className={`flex flex-col h-18 w-28 ${formData.formType === FormType.Select ? "border-primary/40 bg-[#DFE9FD] text-primary" : ""}`}
                        type="button"
                        variant="outline"
                        onClick={() => handleChangeFormType(FormType.Select)}
                    >
                        <ChevronsDown size={18} />
                        {t("dropdown")}
                    </Button>
                    <Button
                        className={`flex flex-col h-18 w-28 ${formData.formType === FormType.File ? "border-primary/40 bg-[#DFE9FD] text-primary" : ""}`}
                        type="button"
                        variant="outline"
                        onClick={() => handleChangeFormType(FormType.File)}
                    >
                        <CloudUpload size={18} />
                        {t("file")}
                    </Button>
                </div>
            </div>

            {formData.formType === FormType.Text && (InputForm)}
            {formData.formType === FormType.Select && (SelectForm)}
            {formData.formType === FormType.File && (FileForm)}

            <div className="flex space-x-4 justify-end">
                <Button className="px-8" type="button" variant="outline" onClick={onCancel}>
                    {t("cancel")}
                </Button>
                <Button className="px-8" type="submit">
                    {t("confirm")}
                </Button>
            </div>
        </form>
    );
}

// node input form item
export default function InputFormItem({ data, nodeId, onChange, onValidate, onVarEvent }) {
    const { t } = useTranslation('flow'); // 使用国际化
    const [isOpen, setIsOpen] = useState(false);
    const [editKey, setEditKey] = useState(""); // 控制编辑模式
    const [foucsUpdate, setFoucsUpdate] = useState(false);
    const [error, setError] = useState(false);

    // 打开弹窗并重置状态
    const handleOpen = () => {
        setEditKey(""); // 新建时不设置为编辑模式
        setIsOpen(true);
    };

    // 关闭弹窗
    const handleClose = () => {
        setIsOpen(false);
    };

    // 提交表单数据，添加或更新表单项
    const scrollRef = useRef(null);
    const handleSubmit = (_data) => {
        const {
            allowMultiple,
            isMultiple,
            displayName: value,
            formType: type,
            isRequired: required,
            options,
            variableName: key,
            filecontent: file_content,
            filepath: file_path,
            fileType: file_type,
            fileTypes: file_types,
            fileContentSize: file_content_size,
            imageFile: image_file,
            audioFile: audio_file
        } = _data;

        const multiple = type === FormType.File ? isMultiple : allowMultiple;
        if (editKey) {
            // 编辑模式，更新表单项
            data.value = data.value.map((opt) =>
                opt.key === editKey
                    ? {
                        key,
                        type,
                        value,
                        required,
                        multiple,
                        options,
                        file_content,
                        file_path,
                        file_type,
                        file_types,
                        file_content_size,
                        image_file,
                        audio_file
                    }
                    : opt
            );
        } else {
            // 新建模式，添加表单项
            data.value = [...data.value, {
                key,
                type,
                value,
                required,
                multiple,
                file_content,
                file_path,
                file_type,
                file_types,
                options,
                file_content_size,
                image_file,
                audio_file
            }];
            setTimeout(() => {
                scrollRef.current?.scrollTo(0, scrollRef.current?.scrollHeight); // 滚动到底部
            }, 0);
        }
        onChange(data.value);
        setFoucsUpdate(!foucsUpdate);
        setIsOpen(false); // 关闭弹窗
    };

    // 当编辑 DragOptions 中的表单项时打开弹窗
    const handleEditClick = (index, option) => {
        const item = data.value[index];
        setEditKey(item.key); // 设置为编辑模式
        setIsOpen(true); // 打开弹窗
    };

    // 更新 DragOptions 的顺序变化
    const handleOptionsChange = (newOptions) => {
        data.value = newOptions.map((el) => {
            return data.value.find((op) => op.key === el.key);
        });
        onChange(data.value);
    };

    // 校验逻辑
    useEffect(() => {
        onValidate(() => {
            if (!data.value.length) {
                setError(true);
                return t("atLeastOneFormItem"); // "至少添加一个表单项"
            }
            setError(false);
            return false;
        });

        return () => onValidate(() => { });
    }, [data.value]);

    const options = useMemo(() => {
        const _options = cloneDeep(data.value)
        return _options.map((el) => {
            // cn
            if (el.type === 'text') {
                el.value = el.value.replace(/{{#(.*?)#}}/g, (a, key) => {
                    return data.varZh?.[key] || key;
                })
            }

            return {
                key: el.key,
                text: el.type === 'file' ? `${el.value}(${el.key},${el.file_content},${el.file_path})` : `${el.value}(${el.key})`,
                type: el.type,
            }
        });
    }, [data.value])

    const { flow } = useFlowStore();
    // 校验变量是否可用
    const validateVarAvailble = () => {
        const errors = data.value.reduce((acc, value) => {
            if (value.type === 'text') {
                value.value.replace(/{{#(.*?)#}}/g, (a, part) => {
                    console.log('a, part :>> ', a, part);
                    const _error = isVarInFlow(nodeId, flow.nodes, part, data.varZh?.[part])
                    _error && acc.push(_error)
                })
            }
            return acc
        }, [])
        return Promise.resolve(errors);
    };

    useEffect(() => {
        onVarEvent && onVarEvent(validateVarAvailble);
        return () => onVarEvent && onVarEvent(() => { });
    }, [data]);

    return (
        <div className="node-item mb-4 nodrag" data-key={data.key}>
            {data.value.length > 0 && (
                <DragOptions
                    scroll
                    ref={scrollRef}
                    options={options}
                    onEditClick={handleEditClick} // 点击编辑时执行的逻辑
                    onChange={handleOptionsChange} // 拖拽排序后的更新
                />
            )}
            <Button
                onClick={handleOpen}
                variant="outline"
                className="border-primary text-primary mt-2"
            >
                {data.label}
            </Button>
            {error && <p className="text-red-500 text-sm">{t("atLeastOneFormItem")}</p>}

            <Dialog open={isOpen} onOpenChange={setIsOpen}>
                <DialogContent>
                    <DialogHeader>
                        <DialogTitle>
                            {editKey ? t("editFormItem") : t("addFormItem")}
                        </DialogTitle>
                    </DialogHeader>

                    {isOpen && <Form
                        nodeId={nodeId}
                        nodeData={data}
                        initialData={
                            editKey
                                ? data.value.find((el) => el.key === editKey)
                                : null
                        } // 如果是编辑模式，传入当前表单数据
                        onSubmit={handleSubmit} // 表单提交时回传数据给父组件
                        onCancel={handleClose} // 取消关闭弹窗
                        existingOptions={data.value} // 传递当前所有 options 以检查重复
                    />
                    }
                </DialogContent>
            </Dialog>
        </div>
    );
}