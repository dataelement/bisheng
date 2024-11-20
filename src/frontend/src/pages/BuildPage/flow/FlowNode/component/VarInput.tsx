import { Button } from "@/components/bs-ui/button";
import { Label } from "@/components/bs-ui/label";
import { isVarInFlow } from "@/util/flowUtils";
import { UploadCloud, Variable } from "lucide-react";
import { useEffect, useRef } from "react";
import useFlowStore from "../../flowStore";
import SelectVar from "./SelectVar";

// ' ' -> '&nbsp;'
const htmlDecode = (input) => {
    const doc = new DOMParser().parseFromString(input, "text/html");
    return doc.documentElement.textContent;
}
// '&nbsp;' -> ' ' & 去html
const htmlEncode = (input) => {
    const doc = document.createElement('div');
    doc.textContent = input;
    return doc.innerHTML;
}

const findKeyByValue = (obj, value) => {
    if (!obj) return value
    for (const key in obj) {
        if (obj[key] === value) {
            return key;
        }
    }
    return value;
};

export default function VarInput({ nodeId, itemKey, placeholder = '', flowNode, value, error = false, children = null, onUpload = undefined, onChange, onVarEvent = undefined }) {
    const { textareaRef, handleFocus, handleBlur } = usePlaceholder(placeholder);
    const textAreaHtmlRef = useRef(null);
    const textMsgRef = useRef(value || '');
    const { flow } = useFlowStore()

    const strToHtml = (str, vilidate = false) => {
        let error = ''
        const regex = /{{#(.*?)#}}/g;
        const parts = htmlDecode(str).split(regex);
        const html = parts.map((part, index) => {
            if (index % 2 === 1) {
                const msgZh = flowNode.varZh?.[part] || part;

                if (vilidate) {
                    error = isVarInFlow(nodeId, flow.nodes, part, flowNode.varZh?.[part])
                }
                return `<span class=${error ? "textarea-error" : "textarea-badge"} contentEditable="false">${msgZh}</span>` // 校验逻辑增加id
            }
            return part;
        }).join('');

        return [html, error]
    }

    const htmlToStr = (html) => {
        return htmlDecode(html.replace(/<span[^>]*>.*?<\/span>/g, (match) => {
            const innerText = match.replace(/<[^>]+>/g, '');
            // label -> value
            return `{{#${findKeyByValue(flowNode.varZh, innerText)}#}}`; // 将 span 内容转换回表达式格式
        }));
    }

    useEffect(() => {
        textAreaHtmlRef.current = strToHtml(value || '')[0]
        if (textAreaHtmlRef.current) {
            textareaRef.current.innerHTML = textAreaHtmlRef.current;
        } else {
            textareaRef.current.innerHTML = placeholder;
            textareaRef.current.classList.add("placeholder");
        }
    }, [])

    const handleInput = () => {
        textAreaHtmlRef.current = textareaRef.current.innerHTML;
        textMsgRef.current = htmlToStr(textAreaHtmlRef.current)
        onChange(textMsgRef.current);
    }
    // 记录光标位置
    const cursorPositionRef = useRef(0);
    const handleSelection = () => {
        const selection = window.getSelection();
        if (selection.rangeCount > 0) {
            const range = selection.getRangeAt(0);
            const container = textareaRef.current;

            let position = 0;
            // 计算光标在文本中的位置
            const nodes = Array.from(container.childNodes);
            for (const node of nodes) {
                if (node.nodeType === Node.TEXT_NODE) {
                    if (node === range.startContainer) {
                        position += range.startOffset; // 获取当前文本节点中的偏移量
                        break;
                    } else {
                        position += node.textContent.length; // 累加节点的文本长度
                    }
                } else if (node.nodeType === Node.ELEMENT_NODE) {
                    // 对于元素节点直接加上其文本长度
                    // {{##}}.length -> 6
                    position += findKeyByValue(flowNode.varZh, node.textContent).length + 6;
                }
            }
            cursorPositionRef.current = position;
            // console.log('cursorPositionRef :>> ', cursorPositionRef.current);
        }
    };

    // // 在光标位置插入内容
    const handleInsertVariable = (item, _var) => {
        const msg = textMsgRef.current
        // console.log('positon :>> ', cursorPositionRef.current, msg);
        const beforeCursor = msg.slice(0, cursorPositionRef.current);
        const afterCursor = msg.slice(cursorPositionRef.current);
        // // lang zh map
        const key = `${item.id}.${_var.value}`
        const label = `${item.name}/${_var.label}`
        if (flowNode.varZh) {
            flowNode.varZh[key] = label
        } else {
            flowNode.varZh = {
                [key]: label
            }
        }
        const newContent = beforeCursor + `{{#${key}#}}` + afterCursor;
        const newHtmlContent = strToHtml(newContent)[0]

        textMsgRef.current = newContent;
        textAreaHtmlRef.current = newHtmlContent;
        textareaRef.current.innerHTML = textAreaHtmlRef.current;
        cursorPositionRef.current += `{{#${key}#}}`.length
        // console.log('cursorPositionRef:>> ', cursorPositionRef.current);

        onChange(textMsgRef.current);
    };

    const handlePaste = (e) => {
        // fomat text
        e.preventDefault();  // 阻止默认粘贴行为
        const text = e.clipboardData.getData('text');  // 从剪贴板中获取纯文本内容
        document.execCommand('insertText', false, text);
    }

    // 校验变量是否可用
    const validateVarAvailble = () => {
        const value = textMsgRef.current;
        const [html, error] = strToHtml(value || '', true)
        textAreaHtmlRef.current = html
        textareaRef.current.innerHTML = textAreaHtmlRef.current;
        return error
    }
    useEffect(() => {
        onVarEvent && onVarEvent(validateVarAvailble)
        return () => onVarEvent && onVarEvent(() => { })
    }, [])

    return <div className={`nodrag mt-2 flex flex-col w-full relative rounded-md border bg-search-input text-sm shadow-sm ${error ? 'border-red-500' : 'border-input'}`}>
        <div className="flex justify-between gap-1 border-b px-2 py-1">
            <Label className="bisheng-label text-xs" onClick={validateVarAvailble}>变量输入</Label>
            <div className="flex gap-2">
                <SelectVar nodeId={nodeId} itemKey={itemKey} onSelect={handleInsertVariable}>
                    <Variable size={16} className="text-muted-foreground hover:text-gray-800" />
                </SelectVar>
                {onUpload && <Button variant="ghost" className="p-0 h-4 text-muted-foreground" onClick={onUpload}>
                    <UploadCloud size={16} />
                </Button>}
            </div>
        </div>
        <div
            ref={textareaRef}
            contentEditable
            onInput={handleInput}
            onClick={handleSelection}
            onKeyUp={handleSelection}
            onPaste={handlePaste}
            onFocus={handleFocus}
            onBlur={handleBlur}
            className="nowheel bisheng-richtext px-3 py-2 whitespace-pre-line min-h-[80px] max-h-24 overflow-y-auto overflow-x-hidden border-none outline-none bg-search-input rounded-md dark:text-gray-50 placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
        // value={value.msg}
        // onChange={(e) => setValue({ ...value, msg: e.target.value })}
        ></div>
        {children}
    </div>
};


function usePlaceholder(placeholder) {
    const divRef = useRef(null);

    const handleFocus = () => {
        if (divRef.current && divRef.current.innerHTML.trim() === placeholder) {
            divRef.current.innerHTML = "";
            divRef.current.classList.remove("placeholder");
        }
    };

    const handleBlur = () => {
        if (divRef.current && divRef.current.innerHTML.trim() === "") {
            divRef.current.innerHTML = placeholder;
            divRef.current.classList.add("placeholder");
        }
    };

    useEffect(() => {
        if (!placeholder) return
        if (divRef.current) {
            // 添加事件监听
            divRef.current.addEventListener("focus", handleFocus);
            divRef.current.addEventListener("blur", handleBlur);

            // 清理事件监听
            return () => {
                if (divRef.current) {
                    divRef.current.removeEventListener("focus", handleFocus);
                    divRef.current.removeEventListener("blur", handleBlur);
                }
            };
        }
    }, [placeholder]);

    return { textareaRef: divRef, handleFocus, handleBlur };
}


