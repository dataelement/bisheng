import { Button } from "@/components/bs-ui/button";
import { UploadCloud, Variable } from "lucide-react";
import { useEffect, useRef } from "react";
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

export default function VarInput({ nodeId, itemKey, flowNode, value, children = null, onUpload = undefined, onChange }) {
    const textareaRef = useRef(null);
    const textAreaHtmlRef = useRef(null);
    const textMsgRef = useRef(value || '');

    const strToHtml = (str) => {
        const regex = /{{#(.*?)#}}/g;
        const parts = htmlDecode(str).split(regex);
        return parts.map((part, index) => {
            if (index % 2 === 1) {
                const msgZh = flowNode.varZh?.[part] || part;
                return `<span class="textarea-badge" contentEditable="false">${msgZh}</span>` // 校验逻辑增加id
            }
            return part;
        }).join('');
    }

    const htmlToStr = (html) => {
        return htmlDecode(html.replace(/<span[^>]*>.*?<\/span>/g, (match) => {
            const innerText = match.replace(/<[^>]+>/g, '');
            // label -> value
            return `{{#${findKeyByValue(flowNode.varZh, innerText)}#}}`; // 将 span 内容转换回表达式格式
        }));
    }

    useEffect(() => {
        textAreaHtmlRef.current = strToHtml(value || '')
        textareaRef.current.innerHTML = textAreaHtmlRef.current;
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
            console.log('object :>> ', cursorPositionRef.current);
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
        const newHtmlContent = strToHtml(newContent)

        textMsgRef.current = newContent;
        textAreaHtmlRef.current = newHtmlContent;
        textareaRef.current.innerHTML = textAreaHtmlRef.current;
        cursorPositionRef.current += `{{#${key}#}}`.length
        console.log('object 2:>> ', cursorPositionRef.current);

        onChange(textMsgRef.current);
    };

    return <div className="nodrag mt-2 flex flex-col min-h-[80px] w-full relative rounded-md border border-input bg-search-input text-sm shadow-sm">
        <div
            ref={textareaRef}
            contentEditable
            onInput={handleInput}
            onClick={handleSelection}
            onKeyUp={handleSelection}
            className="px-3 py-2 border-none outline-none bg-search-input text-[#111] rounded-md dark:text-gray-50 placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
        // value={value.msg}
        // onChange={(e) => setValue({ ...value, msg: e.target.value })}
        // placeholder="Enter your message..."
        ></div>

        <div className="absolute top-0 right-2 flex gap-1">
            <SelectVar nodeId={nodeId} itemKey={itemKey} onSelect={handleInsertVariable}>
                <Variable size={18} className="text-muted-foreground hover:text-gray-800" />
            </SelectVar>
            {onUpload && <Button variant="ghost" className="p-0 h-8 text-muted-foreground" onClick={onUpload}>
                <UploadCloud size={18} />
            </Button>}
        </div>

        {children}
    </div>
};
