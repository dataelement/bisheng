import { getLinsightTools, getPersonalKnowledgeInfo, readFileLibDatabase } from "@/controllers/API";
import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import { useQuery } from "react-query";
import Vditor from "vditor";
import "vditor/dist/index.css";
import SopToolsDown from "./SopToolsDown";

interface MarkdownProps {
    defaultValue: string,
    onChange?: any;
}

interface MarkdownRef {
    getValue: () => string;
}

const SopMarkdown = forwardRef<MarkdownRef, MarkdownProps>((props, ref) => {
    const { tools, defaultValue, onChange } = props;

    const veditorRef = useRef<any>(null);
    const inserRef = useRef<any>(null);
    const boxRef = useRef<any>(null);
    const scrollBoxRef = useRef<any>(null);

    const { nameToValueRef, valueToNameRef, buildTreeData: toolOptions } = useSopTools(tools)

    useEffect(() => {
        const vditorDom = document.getElementById('sop-vditor');
        if (!vditorDom) return

        const vditor = new Vditor("sop-vditor", {
            value: defaultValue,
            cdn: location.origin + __APP_ENV__.BASE_URL + '/vditor',
            toolbar: [],
            cache: {
                enable: false
            },
            height: boxRef.current.clientHeight,
            mode: "wysiwyg",
            placeholder: "",
            after: () => {
                veditorRef.current = vditor;
                scrollBoxRef.current = vditorDom.querySelector('.vditor-reset');
            },
            input: onChange,
            hint: {
                parse: false, // 必须
                placeholder: {
                    delay: 2000,
                    text: "输入 @ 添加知识库、文件或工具",
                },
                extend: [{
                    key: '@',
                    callback(open, insert) {
                        const pos = vditor.getCursorPosition()
                        // console.log('pos :>> ', open, pos);
                        setMenuPosition({ left: pos.left, top: pos.top + 28 });
                        setMenuOpen(open);

                        inserRef.current = insert;
                    }
                }]
            },
            preview: {
                delay: 500,
                markdown: {
                    toc: true,
                    mark: true,
                    footnotes: true,
                    autoSpace: true,
                },
                math: {
                    inlineDigit: true,
                }
            },
            tab: "\t",
        });

        return () => {
            veditorRef.current?.destroy();
            veditorRef.current = null
        };
    }, []);

    useEffect(() => {
        // 用户输入同步value to markdown
        if (defaultValue === '' || defaultValue) {
            // 回显值
            veditorRef.current?.setValue(replaceMarkersToBraces(defaultValue, valueToNameRef.current, nameToValueRef.current))
        }

    }, [])

    // 暴露方法给父组件
    useImperativeHandle(ref, () => ({
        getValue: () => {
            return replaceBracesToMarkers(veditorRef.current?.getValue(), nameToValueRef.current)
        },
    }));

    const [menuOpen, setMenuOpen] = useState(false);
    const [menuPosition, setMenuPosition] = useState({ top: 0, left: 0 });

    const handleChange = (val) => {
        inserRef.current(`{{@${val.label}@}}`);
        setMenuOpen(false)
    }

    useAtTip(scrollBoxRef)

    return <div ref={boxRef} className="relative border rounded-md  h-[calc(100vh-420px)]">
        <div id="sop-vditor" className="linsight-vditor rounded-md border-none" />
        {/* 工具选择 */}
        <div>
            <SopToolsDown
                open={menuOpen}
                position={menuPosition}
                options={toolOptions}
                onChange={handleChange}
                onClose={() => setMenuOpen(false)}
            />
        </div>
    </div >;
});


export default SopMarkdown;


// 工具整合
const useSopTools = (tools) => {
    const nameToValueRef = useRef({});
    const valueToNameRef = useRef({});
    const files = []
    const { data: orgTools } = useQuery({
        queryKey: ['OrgTools'],
        queryFn: () => readFileLibDatabase({ page: 1, pageSize: 400, type: 0 }),
        select(data) {
            return data?.data;
        },
        refetchOnWindowFocus: false,
        refetchOnReconnect: false,
    });

    const { data: personalTool } = useQuery({
        queryKey: ['PersonalTools'],
        queryFn: () => getPersonalKnowledgeInfo(),
        refetchOnWindowFocus: false,
        refetchOnReconnect: false,
    });

    const { data: linsightTools } = useQuery({
        queryKey: ['LinsightTools'],
        queryFn: getLinsightTools,
        refetchOnWindowFocus: false,
        refetchOnReconnect: false,
        refetchOnMount: false,
    });

    // 整合数据为二级树结构
    const buildTreeData = useMemo(() => {
        const tree: { label: string; value: string; desc: string; children: any[] }[] = [];

        // 1. 转换files数据
        if (files && files.length > 0) {
            const fileNode = {
                label: "上传文件",
                value: "",
                desc: '',
                children: []
            };
            fileNode.children = files.map(file => {
                const name = file.file_name;
                const value = `${file.file_name}的文件储存信息：{"文件储存在语义检索库中的id":"${file.file_id}","文件储存地址":"./${decodeURIComponent(file.markdown_filename)}"}`;
                nameToValueRef.current[name] = value;
                valueToNameRef.current[value] = name;
                return {
                    label: file.file_name,
                    value: file.file_id,
                    desc: '',
                    children: []
                }
            });
            tree.push(fileNode);
        }

        // 2. 转换orgTools数据
        if (orgTools && orgTools.length > 0) {
            tree.push({
                label: "组织知识库",
                value: "org_knowledge_base", // 使用特殊标识避免ID冲突
                desc: '',
                children: orgTools.map(tool => {
                    const name = tool.name;
                    const value = `${tool.name}的储存信息：{"知识库储存在语义检索库中的id":"${tool.id}"}`
                    nameToValueRef.current[name] = value;
                    valueToNameRef.current[value] = name;
                    return {
                        label: tool.name,
                        value: tool.id,
                        desc: tool.description,
                        children: []
                    }
                })
            });
        }

        // 3. 转换PersonalTool数据（单对象转数组）
        if (personalTool && personalTool[0]) {
            tree.push({
                label: personalTool[0].name,
                value: personalTool[0].id,
                desc: '',
                children: [] // 个人知识库没有子节点
            });
            const name = personalTool[0].name;
            const value = `${personalTool[0].name}的储存信息：{"知识库储存在语义检索库中的id":"${personalTool[0].id}"}`
            nameToValueRef.current[name] = value;
            valueToNameRef.current[value] = name;
        }

        // 4. 转换linsightTools数据
        if (linsightTools && linsightTools.length > 0) {
            linsightTools.forEach(toolGroup => {
                tree.push({
                    label: toolGroup.name,
                    value: toolGroup.id,
                    desc: toolGroup.description,
                    children: (toolGroup.children || []).map(child => {
                        const name = child.name;
                        const value = `${child.tool_key}`
                        nameToValueRef.current[name] = value;
                        valueToNameRef.current[value] = name;
                        return {
                            label: child.name,
                            value: child.tool_key,
                            desc: child.desc,
                            children: [] // 二级节点无子节点
                        }
                    })
                });
            });
        }
        // 5. 转换tools数据
        if (tools && tools.length > 0) {
            tools.forEach(toolGroup => {
                tree.push({
                    label: toolGroup.name,
                    value: toolGroup.id,
                    desc: toolGroup.description,
                    children: (toolGroup.children || []).map(child => {
                        const name = child.name;
                        const value = `${child.tool_key}`
                        nameToValueRef.current[name] = value;
                        valueToNameRef.current[value] = name;
                        return {
                            label: child.name,
                            value: child.tool_key,
                            desc: child.desc,
                            children: []
                        }
                    })
                });
            });
        }

        return tree;
    }, [linsightTools, personalTool, orgTools, files, tools]);

    console.log('整合后的树结构:', buildTreeData);
    return { nameToValueRef, valueToNameRef, buildTreeData };
};

// 滚动隐藏@标记
const useAtTip = (scrollBoxRef) => {
    useEffect(() => {

        const handleScroll = () => {
            const atDom = document.querySelector('#vditor-placeholder-at');
            if (atDom) {
                atDom.style.display = 'none';
            }
        }
        if (scrollBoxRef.current) {
            scrollBoxRef.current.addEventListener('scroll', handleScroll);
        }

        return () => {
            if (scrollBoxRef.current) {
                scrollBoxRef.current.removeEventListener('scroll', handleScroll);
            }
        }
    }, [scrollBoxRef.current])
}

/**
 * 正向替换：将 @标记@ 替换为 {{value}} 格式
 * @param {string} inputStr - 输入字符串
 * @param {Object} valueToNameMap - 映射对象 {id: value}
 * @returns {string} - 替换后的字符串
 */
function replaceMarkersToBraces(inputStr, valueToNameMap, nameToValueMap) {
    const regex = /@([^@]+)@/g;
    return inputStr.replace(regex, (match, id) => {
        // 检查映射中是否存在该ID
        if (Object.prototype.hasOwnProperty.call(valueToNameMap, id)) {
            return `{{@${valueToNameMap[id]}@}}`;
        }
        // 反推回原始值
        if (Object.prototype.hasOwnProperty.call(nameToValueMap, id)) {
            return `{{@${id}@}}`;
        }
        console.warn('转换ui时未找到对应的ID  :>> ', valueToNameMap, id);
        return `@${id}@`; // 未找到时保留原始ID
    });
}

/**
 * 反向替换：将 {{value}} 替换为 @id@ 格式
 * @param {string} inputStr - 输入字符串
 * @param {Object} nameToValueMap - 映射对象 {value: id}
 * @returns {string} - 替换后的字符串
 */
function replaceBracesToMarkers(inputStr, nameToValueMap) {
    const regex = /\{\{[@#]([^{}]+)[@#]\}\}/g;
    return inputStr.replace(regex, (match, value) => {
        // 检查映射中是否存在该值
        if (Object.prototype.hasOwnProperty.call(nameToValueMap, value)) {
            return `@${nameToValueMap[value]}@`;
        }
        console.warn('转换sop时未找到对应的工具  :>> ', nameToValueMap, value);
        return `@${value}@`; // 未找到时保留原始值
    });
}
