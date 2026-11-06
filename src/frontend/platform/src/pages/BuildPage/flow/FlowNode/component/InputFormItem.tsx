// @ts-strict-ignore
import { Button } from '@bisheng/ui';

import { Dialog,DialogContent,DialogHeader,DialogTitle } from "@/components/bs-ui/dialog";
import { acceptsImages } from "@/util/fileAcceptUtils";
import { isVarInFlow } from "@/util/flowUtils";
import { generateUUID } from "@/utils";
import { cloneDeep } from "lodash-es";
import { useEffect,useMemo,useRef,useState } from "react";
import { useTranslation } from "react-i18next";
import useFlowStore from "../../flowStore";
import DragOptions from "./DragOptions";

// node input form item
import { InputFormEditor as Form } from "./InputFormEditor";
import { FileProcessingStrategy,FormOption,FormType,optionToModes } from "./inputFormTypes";

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
            variableName,
            filecontent: file_content,
            filepath: file_path,
            fileType: file_type,
            fileContentSize: file_content_size,
            imageFile: image_file,
            processingOption: file_parse_option // single named option (F038)
        } = _data;
        // The 3 named options map to fixed atomic-mode arrays (stored契约).
        const file_parse_mode = optionToModes(file_parse_option);
        const isParse = file_parse_option === FormOption.ParseOnly
            || file_parse_option === FormOption.ParseIngest;
        const isIngest = file_parse_option === FormOption.ParseIngest;

        let key
        if (type === FormType.File) {
            if (isIngest) {
                // 解析(入库)：key 永远等于 variableName（即临时知识库名）
                key = variableName;
            } else {
                key = editKey || `file_${generateUUID(6)}`;
            }
        } else {
            key = variableName || `file_${generateUUID(6)}`;
        }
        const multiple = type === FormType.File ? isMultiple : allowMultiple;

        // 按统一规则清理字段：路径恒留；图片看上传类型；解析结果看是否解析。
        let cleanedImageFile = image_file;
        let cleanedFileContent = file_content;
        const cleanedFilePath = file_path;
        const cleanedFileContentSize = file_content_size;

        if (type === FormType.File) {
            if (!isParse) {
                cleanedFileContent = '';
            }
            // 图片变量仅在上传类型含图片时保留
            if (!acceptsImages(file_type)) {
                cleanedImageFile = '';
            }
            // 文件路径恒留（path 恒暴露），不清空 cleanedFilePath
        }

        // 创建新的表单项对象
        const newItem = {
            key,
            type,
            value,
            required,
            multiple,
            options,
            file_content: cleanedFileContent,
            file_path: cleanedFilePath,
            file_type,
            file_content_size: cleanedFileContentSize,
            image_file: cleanedImageFile,
            file_parse_mode
        };

        let newValue;

        if (editKey) {
            // 编辑模式：更新表单项
            newValue = data.value.map((opt) =>
                opt.key === editKey ? newItem : opt
            );
        } else {
            // 新建模式：添加表单项
            newValue = [...data.value, newItem];
            setTimeout(() => {
                scrollRef.current?.scrollTo(0, scrollRef.current?.scrollHeight); // 滚动到底部
            }, 0);
        }

        // 通过 onChange 回调更新数据
        onChange(newValue);
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
        const newValue = newOptions
            .map((el) => data.value.find((op) => op.key === el.key))
            .filter(Boolean);

        // 通过 onChange 更新数据
        onChange(newValue);
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

            // 构建变量列表
            let variableList = el.key;

            if (el.type === 'file') {
                // 文件类型按统一规则列出产出变量：解析结果(解析时) / 图片(含图片类型) / 路径(恒) / 临时库名(入库时)
                const variableParts = [];
                const arr = Array.isArray(el.file_parse_mode)
                    ? el.file_parse_mode
                    : (el.file_parse_mode ? [el.file_parse_mode] : []);
                const isParse = arr.includes(FileProcessingStrategy.ParseContent);
                const isIngest = arr.includes(FileProcessingStrategy.TempKnowledge);
                const isImageCapable = acceptsImages(el.file_type);

                if (isParse && el.file_content) variableParts.push(el.file_content);
                if (isImageCapable && el.image_file) variableParts.push(el.image_file);
                if (el.file_path) variableParts.push(el.file_path);
                if (isIngest) variableParts.push(el.key);

                if (variableParts.length > 0) {
                    variableList = variableParts.join(', ');
                }
            }

            const text = `${el.value}（${variableList}）`;

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
            <Button onClick={handleOpen} variant="outlined" className="border-primary text-primary mt-2" color="default">
                {t(`${i18nPrefix}label`)}
            </Button>
            {error && <p className="text-red-500 text-sm">{t("atLeastOneFormItem")}</p>}

            <Dialog open={isOpen} onOpenChange={setIsOpen}>
                <DialogContent className="flex max-h-[calc(100vh-64px)] flex-col">
                    <DialogHeader>
                        <DialogTitle>
                            {editKey ? t("editFormItem") : t("addFormItem")}
                        </DialogTitle>
                    </DialogHeader>

                    {isOpen && <Form
                        key={editKey || 'new'}
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