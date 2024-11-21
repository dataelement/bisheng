import { Button } from "@/components/bs-ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { Input } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { Switch } from "@/components/bs-ui/switch";
import { QuestionTooltip } from "@/components/bs-ui/tooltip";
import { ChevronsDown, CloudUpload, Type } from "lucide-react";
import { useEffect, useState } from "react";
import DragOptions from "./DragOptions";

const enum FormType {
    Text = "text",
    Select = "select",
    File = "file",
}

function Form({ initialData, onSubmit, onCancel, existingOptions }) {
    const namePlaceholders = {
        [FormType.Text]: "例如“姓名”",
        [FormType.Select]: "例如“保险类别”",
        [FormType.File]: "例如“请上传去年财报”",
    }

    const [formData, setFormData] = useState({
        formType: FormType.Text,
        displayName: "",
        variableName: "",
        isRequired: true,
        allowMultiple: false,  // 允许多选开关
        options: [],  // 选项，适用于下拉框
    });
    const [errors, setErrors] = useState<any>({}); // 用于存储校验错误

    // 当 initialData 存在时，填充表单数据（用于编辑模式）
    useEffect(() => {
        if (initialData) {
            const {
                type: formType,
                value: displayName,
                key: variableName,
                required: isRequired,
                multi: allowMultiple,
                options = [] } = initialData
            setFormData({
                formType,
                displayName, // 展示名称
                variableName, // 变量名称
                isRequired, // 是否必填
                allowMultiple, // 允许多选
                options, // 选项，适用于下拉框
            });
        }
    }, [initialData]);

    useEffect(() => {
        if (initialData) return
        // 初始化变量名
        const names = {
            [FormType.Text]: "text_input",
            [FormType.Select]: "category",
            [FormType.File]: "file",
        }
        let initialVarName = names[formData.formType];
        let counter = 1;
        while (existingOptions?.some(opt => opt.key === initialVarName)) {
            counter += 1;
            initialVarName = `${initialVarName}${counter}`;
        }
        setFormData((prevData) => ({
            ...prevData,
            variableName: initialVarName,
        }));
    }, [initialData, formData.formType])

    const validateForm = () => {
        const newErrors: any = {};

        // 校验展示名称
        if (!formData.displayName.trim()) {
            newErrors.displayName = "展示名称不可为空";
        } else if (formData.displayName.length > 50) {
            newErrors.displayName = "展示名称不能超过 50 个字符";
        }

        // 校验变量名称
        if (!formData.variableName.trim()) {
            newErrors.variableName = "变量名称不可为空";
        } else if (!/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(formData.variableName)) {
            newErrors.variableName = "变量名称只能包含英文字符、数字和下划线，且不能以数字开头";
        } else if (formData.variableName.length > 50) {
            newErrors.variableName = "变量名称不能超过 50 个字符";
        } else if (existingOptions?.some(opt => opt.key === formData.variableName)) {
            newErrors.variableName = "变量名称已存在";
        }

        // 校验选项长度
        if (formData.formType === FormType.Select && !formData.options.length) {
            newErrors.options = "至少添加 1 个选项";
        }

        setErrors(newErrors);
        return Object.keys(newErrors).length === 0; // 如果没有错误，返回 true
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

    return (
        <form onSubmit={handleFormSubmit} className="space-y-4">
            <div>
                <Label className="bisheng-label">表单项类型</Label>
                <div className="flex gap-4 justify-between mx-6 mt-2">
                    <Button
                        className={`flex flex-col h-18 w-28 ${formData.formType === FormType.Text ? "border-primary/40 bg-[#DFE9FD] text-primary" : ""}`}
                        type="button"
                        variant="outline"
                        onClick={() => setFormData({ ...formData, formType: FormType.Text })}
                    >
                        <Type size={18} />
                        文本输入
                    </Button>
                    <Button
                        className={`flex flex-col h-18 w-28 ${formData.formType === FormType.Select ? "border-primary/40 bg-[#DFE9FD] text-primary" : ""}`}
                        type="button"
                        variant="outline"
                        onClick={() => setFormData({ ...formData, formType: FormType.Select })}
                    >
                        <ChevronsDown size={18} />
                        下拉选项
                    </Button>
                    <Button
                        className={`flex flex-col h-18 w-28 ${formData.formType === FormType.File ? "border-primary/40 bg-[#DFE9FD] text-primary" : ""}`}
                        type="button"
                        variant="outline"
                        onClick={() => setFormData({ ...formData, formType: FormType.File })}
                    >
                        <CloudUpload size={18} />
                        文件
                    </Button>
                </div>
            </div>
            <div>
                <Label className="flex items-center bisheng-label">
                    展示名称
                    <QuestionTooltip content={"用户会话页面展示此名称"} />
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
                    变量名称
                    <QuestionTooltip content={formData.formType === FormType.File ? "用于存储用户会话页面填写的内容，可在临时会话文件列表中选择此变量" : "用于存储用户会话页面填写的内容，可在其他节点中引用此变量"} />
                </Label>
                <Input
                    className={`mt-2 ${errors.variableName ? "border-red-500" : ""}`}
                    id="variableName"
                    placeholder="请输入变量名"
                    value={formData.variableName}
                    onChange={(e) => setFormData({ ...formData, variableName: e.target.value })}
                />
                {errors.variableName && <p className="text-red-500 text-sm">{errors.variableName}</p>}
            </div>

            {formData.formType === FormType.Select && (
                <div>
                    <Label className="bisheng-label">选项</Label>
                    <DragOptions
                        options={formData.options}
                        onChange={updateOptions}
                    />
                    {errors.options && <p className="text-red-500 text-sm">{errors.options}</p>}
                </div>
            )}

            {formData.formType === FormType.Select && (
                <div className="flex items-center space-x-2">
                    <Label className="bisheng-label">允许多选</Label>
                    <Switch
                        checked={formData.allowMultiple}
                        onCheckedChange={(checked) => setFormData({ ...formData, allowMultiple: checked })}
                    />
                </div>
            )}

            <div className="flex items-center space-x-2">
                <Label className="bisheng-label">是否必填</Label>
                <Switch
                    checked={formData.isRequired}
                    onCheckedChange={(checked) => setFormData({ ...formData, isRequired: checked })}
                />
            </div>

            <div className="flex space-x-4 justify-end">
                <Button className="px-8" type="button" variant="outline" onClick={onCancel}>
                    取消
                </Button>
                <Button className="px-8" type="submit">
                    确认
                </Button>
            </div>
        </form>
    );
}
export default function InputFormItem({ data, onChange, onValidate }) {
    const [isOpen, setIsOpen] = useState(false);
    const [editKey, setEditKey] = useState(''); // 控制编辑模式
    const [foucsUpdate, setFoucsUpdate] = useState(false);

    // 打开弹窗并重置状态
    const handleOpen = () => {
        setEditKey(''); // 新建时不设置为编辑模式
        setIsOpen(true);
    };

    // 关闭弹窗
    const handleClose = () => {
        setIsOpen(false);
    };

    // 提交表单数据，添加或更新表单项
    const handleSubmit = (_data) => {
        const {
            allowMultiple: multi,
            displayName: value,
            formType: type,
            isRequired: required,
            options,
            variableName: key
        } = _data
        if (editKey) {
            // 编辑模式，更新表单项
            data.value = data.value.map((opt) => (opt.key === editKey ? {
                key,
                type,
                value,
                required,
                multi,
                options
            } : opt))
        } else {
            data.value.push({
                key,
                type,
                value,
                required,
                multi,
                options
            })
            // 新建模式，添加表单项
        }
        onChange(data.value);
        setFoucsUpdate(!foucsUpdate);
        setIsOpen(false); // 关闭弹窗
    };

    // 当编辑 DragOptions 中的表单项时打开弹窗
    const handleEditClick = (index, option) => {
        const item = data.value[index]
        setEditKey(item.key); // 设置为编辑模式
        // setFormData(option); // 设置要编辑的表单数据
        setIsOpen(true); // 打开弹窗
    };

    // 更新 DragOptions 的顺序变化
    const handleOptionsChange = (newOptions) => {
        data.value = newOptions.map(el => {
            return data.value.find(op => op.key === el.key)
        })
        onChange(data.value);
    };

    const [error, setError] = useState(false)
    useEffect(() => {
        onValidate(() => {
            if (!data.value.length) {
                setError(true)
                return '至少添加一个表单项'
            }
            setError(false)
            return false
        })
        return () => onValidate(() => {})
    }, [data.value])

    return (
        <div className="node-item mb-4 nodrag" data-key={data.key}>
            {data.value.length > 0 && (
                <DragOptions
                    options={data.value.map(el => ({
                        key: el.key,
                        text: `${el.value}(${el.key})`,
                        type: el.type
                    }))}
                    onEditClick={handleEditClick} // 点击编辑时执行的逻辑
                    onChange={handleOptionsChange} // 拖拽排序后的更新
                />
            )}
            <Button onClick={handleOpen} variant='outline' className="border-primary text-primary mt-2">
                {data.label}
            </Button>
            {error && <p className="text-red-500 text-sm">至少添加一个表单项</p>}

            <Dialog open={isOpen} onOpenChange={setIsOpen}>
                <DialogContent>
                    <DialogHeader>
                        <DialogTitle>{editKey ? "修改表单项" : "添加表单项"}</DialogTitle>
                    </DialogHeader>

                    <Form
                        initialData={editKey ? data.value.find(el => el.key === editKey) : null} // 如果是编辑模式，传入当前表单数据
                        onSubmit={handleSubmit} // 表单提交时回传数据给父组件
                        onCancel={handleClose} // 取消关闭弹窗
                        existingOptions={data.value} // 传递当前所有 options 以检查重复
                    />
                </DialogContent>
            </Dialog>
        </div>
    );
}