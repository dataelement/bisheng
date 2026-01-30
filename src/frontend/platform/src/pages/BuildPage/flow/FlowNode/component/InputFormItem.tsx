import { Button } from "@/components/bs-ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { Input } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { Switch } from "@/components/bs-ui/switch";
import { QuestionTooltip } from "@/components/bs-ui/tooltip";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select";
import { isVarInFlow } from "@/util/flowUtils";
import { cloneDeep } from "lodash-es";
import { ChevronsDown, CloudUpload, Type } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import useFlowStore from "../../flowStore";
import DragOptions from "./DragOptions";
import FileTypeSelect from "./FileTypeSelect";
import InputItem from "./InputItem";
import VarInput from "./VarInput";
import { t } from "i18next";

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

// 文件处理策略枚举
const enum FileProcessingStrategy {
    TempKnowledge = "ingest_to_temp_kb",  // 存入临时知识库
    ParseContent = "extract_text",    // 解析文件内容
    OriginalFile = "keep_raw",    // 不解析（原始文件）
}


function Form({ nodeId, nodeData, initialData, onSubmit, onCancel, existingOptions }) {
    const { t } = useTranslation('flow');
    const namePlaceholders = {
        [FormType.Text]: t("nameExample"), // 例如"姓名"
        [FormType.Select]: t("categoryExample"), // 例如"保险类别"
        [FormType.File]: t("uploadExample"), // 例如"请上传去年财报"
    };
    const processingStrategyOptions = useMemo(() => [
        { value: FileProcessingStrategy.TempKnowledge, label: t("temporaryKnowledgeBase") },
        { value: FileProcessingStrategy.ParseContent, label: t("parseFile") },
        { value: FileProcessingStrategy.OriginalFile, label: t("notParse") },
    ], [t]);
    const [formData, setFormData] = useState({
        formType: FormType.Text,
        displayName: "",
        variableName: "",
        filecontent: '',
        filepath: '',
        fileType: 'all',
        fileContentSize: 15000,
        imageFile: '',
        isMultiple: true, // default value for multiple file upload
        isRequired: true,
        allowMultiple: false,  // Allow multiple file uploads
        options: [],  // Options for Select input
        processingStrategy: FileProcessingStrategy.TempKnowledge, // 文件处理策略
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
    const oldStrategyRef = useRef("");

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
                file_path: filepath,
                file_content_size: fileContentSize,
                image_file: imageFile,
                file_parse_mode: processingStrategy,
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
                filepath,
                fileContentSize,
                imageFile,
                isMultiple: allowMultiple,
                processingStrategy: processingStrategy || FileProcessingStrategy.TempKnowledge
            });

            editRef.current = true
            oldFormTypeRef.current = formType
            oldVarNameRef.current = variableName;
            oldcontentNameRef.current = filecontent;
            oldPathNameRef.current = filepath;
            oldImageFileRef.current = imageFile;
            oldStrategyRef.current = processingStrategy;
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
        let counter = 1;
        let initialFileContentCounter = 1;
        let initialFilePathCounter = 1;
        let initialFileImageCounter = 1
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
        // 变量重命名
        setFormData((prevData) => ({
            ...prevData,
            variableName: initialVarName,
            filecontent: initialFileContent,
            filepath: initialFilePath,
            imageFile: initialFileImage
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
            // 根据文件类型和处理策略验证不同的字段
            if (formData.fileType === 'all') {
                // 全部类型文件
                if (formData.processingStrategy === FileProcessingStrategy.TempKnowledge) {
                    // 存入临时知识库 - 需要验证 variableName
                    // 上面已经验证过了
                } else if (formData.processingStrategy === FileProcessingStrategy.ParseContent) {
                    // 解析文件内容 - 验证解析结果变量名称和长度
                    if (!formData.filecontent.trim()) {
                        newErrors.filecontent = "variableNameRequired";
                    } else if (!/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(formData.filecontent)) {
                        newErrors.filecontent = "variableNameInvalid";
                    } else if (formData.filecontent.length > 50) {
                        newErrors.filecontent = t("variableNameTooLong");
                    } else if (
                        existingOptions?.some(opt => opt.type === 'file'
                            && opt.file_content === formData.filecontent)
                        && formData.filecontent !== oldcontentNameRef.current
                    ) {
                        newErrors.filecontent = t("variableNameExists");
                    }
                } else if (formData.processingStrategy === FileProcessingStrategy.OriginalFile) {
                    // 不解析（原始文件）- 验证图片变量名称和文件路径变量名称
                    const _error = validateImageFileVariableName(formData.imageFile, existingOptions);
                    if (_error) {
                        newErrors.imageFile = _error
                    }

                    // 验证文件路径变量名称
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
                }
            } else {
                // 文档类型文件
                if (formData.processingStrategy === FileProcessingStrategy.OriginalFile) {
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
                }
            }
        }


        setErrors(newErrors);
        return Object.keys(newErrors).length === 0;
    };

    const validateImageFileVariableName = (varName, existingOptions) => {
        const errors = [];

        // 1. 非空检查
        if (!varName || !varName.trim()) {
            return t('variableNameCannotBeEmpty');
        }

        // 2. 不能以数字开头
        if (/^\d/.test(varName)) {
            return t('variableNameCannotStartWithNumber');
        }

        // 3. 只能包含英文字符、数字和下划线
        if (!/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(varName)) {
            return t('variableNameContainsInvalidCharacters');
        }

        // 4. 长度不超过50
        if (varName.length > 50) {
            return t('variableNameTooLong');
        }

        // 5. 不能重复
        if (existingOptions?.some(opt => opt.type === 'file'
            && opt.image_file === varName)
            && varName !== oldImageFileRef.current) {
            return t('variableNameAlreadyExists');
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

    // 处理文件类型变化
    const handleFileTypeChange = (fileType) => {
        // 当文件类型从 all 变为其他时，重置处理策略为默认值
        if (formData.fileType === 'all' && fileType !== 'all') {
            setFormData({ ...formData, fileType, processingStrategy: FileProcessingStrategy.TempKnowledge });
        } else {
            setFormData({ ...formData, fileType });
        }
        // 清空相关错误
        setErrors({});
    }

    // 处理文件处理策略变化
    const handleProcessingStrategyChange = (strategy) => {
        setFormData({ ...formData, processingStrategy: strategy });
        // 清空相关错误
        setErrors({});
    }

    // 获取可用的文件处理策略选项
    const getAvailableProcessingStrategies = () => {
        return processingStrategyOptions;

    };

    // 检查是否需要显示某个字段
    const shouldShowField = (fieldType) => {
        if (formData.formType !== FormType.File) return false;

        if (formData.fileType === 'all' || formData.fileType === 'image') {
            // 全部类型和图片类型
            switch (fieldType) {
                case 'tempKnowledge':
                    return formData.processingStrategy === FileProcessingStrategy.TempKnowledge;
                case 'parseContent':
                    return formData.processingStrategy === FileProcessingStrategy.ParseContent;
                case 'imageFile':
                    // 全部类型和图片类型的不解析需要显示图片变量
                    return formData.processingStrategy === FileProcessingStrategy.OriginalFile;
                case 'filePath':
                    // 全部类型和图片类型的不解析需要显示文件路径
                    return formData.processingStrategy === FileProcessingStrategy.OriginalFile;
                default:
                    return false;
            }
        } else {
            // 文档类型文件
            switch (fieldType) {
                case 'tempKnowledge':
                    return formData.processingStrategy === FileProcessingStrategy.TempKnowledge;
                case 'parseContent':
                    return formData.processingStrategy === FileProcessingStrategy.ParseContent;
                case 'filePath':
                    // 文档类型的不解析只显示文件路径
                    return formData.processingStrategy === FileProcessingStrategy.OriginalFile;
                case 'imageFile':
                    // 文档类型不显示图片变量名称
                    return false;
                default:
                    return false;
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
                paramItem={nodeData}
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
            <Label className="bisheng-label">{t('allowMultipleSelect')}</Label>
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
            <Label className="bisheng-label">{t('allowUploadMultipleFiles')}</Label>
            <Switch
                checked={formData.isMultiple}
                onCheckedChange={(checked) => setFormData({ ...formData, isMultiple: checked })}
            />
        </div>

        <FileTypeSelect
            data={{
                label: t('uploadFileTypes'),
                value: formData.fileType,
            }}
            onChange={handleFileTypeChange}
        />

        {/* 文件处理策略选择 - 下拉框 */}
        <div>
            <Label className="flex items-center bisheng-label">
                {t("fileProcessingStrategy")}
                <QuestionTooltip content={t("fileProcessingStrategyTip")} />
            </Label>
            <Select
                value={formData.processingStrategy}
                onValueChange={handleProcessingStrategyChange}
            >
                <SelectTrigger className="mt-2">
                    <SelectValue placeholder={t("selectFile")} />
                </SelectTrigger>
                <SelectContent>
                    {getAvailableProcessingStrategies().map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                            {option.label}
                        </SelectItem>
                    ))}
                </SelectContent>
            </Select>
        </div>

        {/* 存入临时知识库 - 显示临时知识库名称 */}
        {shouldShowField('tempKnowledge') && (
            <div>
                <Label className="flex items-center bisheng-label">
                    {t('tempKnowledgeBaseName')}

                    <QuestionTooltip content={t('tempKnowledgeBaseNameTip')} />
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
        )}

        {/* 解析文件内容 - 显示解析结果长度上限和解析结果变量名称 */}
        {shouldShowField('parseContent') && (
            <>
                <div>
                    <Label className="flex items-center bisheng-label">
                        {t("parseResultName")}
                        <QuestionTooltip content={t("storeVariableName")} />
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
                    label={t('parseLengthLimit')}
                    data={{
                        min: 0,
                        value: formData.fileContentSize,
                    }}
                    onChange={(fileContentSize) => setFormData({ ...formData, fileContentSize })}
                />
                {errors.fileContentSize && <p className="text-red-500 text-sm">{errors.fileContentSize}</p>}
            </>
        )}

        {/* 不解析（原始文件） - 显示图片变量名称和文件路径变量名称（仅全部类型） */}
        {shouldShowField('imageFile') && (
            <div>
                <Label className="flex items-center bisheng-label">
                    {t("imageVariableName")}
                    <QuestionTooltip content={t('extractImages')} />
                </Label>
                <Input
                    className={`mt-2 ${errors.imageFile ? "border-red-500" : ""}`}
                    id="imageFile"
                    placeholder={t("enterVariableName")}
                    value={formData.imageFile}
                    onChange={(e) => setFormData({ ...formData, imageFile: e.target.value })}
                />
                {errors.imageFile && <p className="text-red-500 text-sm">{errors.imageFile}</p>}
            </div>
        )}

        {/* 文件路径变量名称（全部类型的原始文件，或文档类型的原始文件） */}
        {shouldShowField('filePath') && (
            <div>
                <Label className="flex items-center bisheng-label">
                    {t("filePathName")}
                    <QuestionTooltip content={t('storeUploadFiles')} />
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
        )}
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
export default function InputFormItem({ data, nodeId, onChange, onValidate, onVarEvent, i18nPrefix }) {
    const { t } = useTranslation('flow');
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
            fileContentSize: file_content_size,
            imageFile: image_file,
            processingStrategy: file_parse_mode
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
                        file_content_size,
                        image_file,
                        file_parse_mode
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
                options,
                file_content_size,
                image_file,
                file_parse_mode
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

            // 为文件类型添加处理策略信息
            let text = '';
            if (el.type === 'file') {
                let strategyText = '';
                if (el.file_parse_mode === FileProcessingStrategy.TempKnowledge) {
                    strategyText = t('temporaryKnowledgeBase');
                } else if (el.file_parse_mode === FileProcessingStrategy.ParseContent) {
                    strategyText = t("parseFile");
                } else if (el.file_parse_mode === FileProcessingStrategy.OriginalFile) {
                    strategyText = t("notParse");
                }
                text = `${el.value}(${el.key}, ${strategyText})`;
            } else {
                text = `${el.value}(${el.key})`;
            }

            return {
                key: el.key,
                text,
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
                {t(`${i18nPrefix}label`)}
            </Button>
            {error && <p className="text-red-500 text-sm">{t("atLeastOneFormItem")}</p>}

            <Dialog open={isOpen} onOpenChange={setIsOpen}>
                <DialogContent className="max-h-screen overflow-auto">
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