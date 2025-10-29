import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import Vditor from "vditor";
import "vditor/dist/index.css";
import { useGetBsConfig, useGetLinsightToolList, useGetOrgToolList, useGetPersonalToolList } from '~/data-provider';
import { useLocalize } from '~/hooks';
import { LinsightInfo } from "~/store/linsight";
import { SopStatus } from "./SOPEditor";
import SopToolsDown from "./SopToolsDown";
import { useRecoilValue } from 'recoil';
import store from '~/store';

// 错误工具toolip提示
const ToolErrorTip = () => {
    const localize = useLocalize();
    const [tooltipState, setTooltipState] = useState({
        show: false,
        message: localize('com_sop_tool_error'),
        position: { left: 0, top: 0 }
    });
    const currentElementRef = useRef<HTMLElement | null>(null);
    const tooltipRef = useRef<HTMLDivElement>(null);

    // 处理鼠标移入事件
    const handleMouseOver = (e: MouseEvent) => {
        const target = (e.target as HTMLElement).closest?.('.linsi-error');
        if (!(target instanceof HTMLElement)) return;

        currentElementRef.current = target;
        const rect = target.getBoundingClientRect();
        setTooltipState({
            show: true,
            message: localize('com_sop_tool_not_found'),
            position: {
                left: rect.left + rect.width / 2,
                top: rect.top - 4
            }
        });
    };

    // 处理鼠标移出事件
    const handleMouseOut = (e: MouseEvent) => {
        const relatedTarget = e.relatedTarget as HTMLElement;
        if (
            !relatedTarget ||
            !currentElementRef.current?.contains(relatedTarget) &&
            !tooltipRef.current?.contains(relatedTarget)
        ) {
            setTooltipState(prev => ({ ...prev, show: false }));
        }
    };

    // 处理滚动事件
    const handleScroll = () => {
        if (currentElementRef.current && tooltipState.show) {
            const rect = currentElementRef.current.getBoundingClientRect();
            setTooltipState(prev => ({
                ...prev,
                position: {
                    left: rect.left + rect.width / 2,
                    top: rect.top - 4
                }
            }));
        }
    };

    useEffect(() => {
        const container = document.getElementById('vditor');
        if (!container) return

        container.addEventListener('mouseover', handleMouseOver as EventListener);
        container.addEventListener('mouseout', handleMouseOut as EventListener);
        window.addEventListener('scroll', handleScroll, true);

        return () => {
            container.removeEventListener('mouseover', handleMouseOver as EventListener);
            container.removeEventListener('mouseout', handleMouseOut as EventListener);
            window.removeEventListener('scroll', handleScroll, true);
        };
    }, []);

    return (
        <div
            ref={tooltipRef}
            className={`pointer-events-none fixed transition-opacity ${tooltipState.show ? 'opacity-100' : 'opacity-0'
                }`}
            style={{
                left: tooltipState.position.left,
                top: tooltipState.position.top,
                transform: 'translateX(-50%) translateY(-100%)'
            }}
        >
            <div className="bg-red-100 text-red-500 text-xs px-2 py-1 rounded shadow-lg">
                {tooltipState.message}
                <div className="absolute bottom-0 left-1/2 transform -translate-x-1/2 translate-y-full w-0 h-0 border-l-4 border-r-4 border-t-4 border-l-transparent border-r-transparent border-t-red-100" />
            </div>
        </div>
    );
};

interface MarkdownProps {
    linsight: LinsightInfo,
    disable?: boolean;
}

interface MarkdownRef {
    getValue: () => string;
}

const SopMarkdown = forwardRef<MarkdownRef, MarkdownProps>((props, ref) => {
    const { linsight, disable, onChange } = props;
    const { sop: value = '', inputSop, files, tools } = linsight
    const localize = useLocalize()

    const veditorRef = useRef<any>(null);
    const inserRef = useRef<any>(null);
    const boxRef = useRef<any>(null);
    const scrollBoxRef = useRef<any>(null);
    useAutoHeight(boxRef)

    const { nameToValueRef, valueToNameRef, buildTreeData: toolOptions } = useSopTools(linsight)
    const [RenderingCompleted, setRenderingCompleted] = useState(false);

    const currentLang = useRecoilValue(store.lang);

    // 将应用语言映射为 Vditor 支持的语言
    const mapLangToVditor = (lang: string) => {
        const lower = (lang || 'en').toLowerCase();
        if (lower.startsWith('zh')) return 'zh_CN';
        if (lower.startsWith('ja')) return 'ja_JP';
        if (lower.startsWith('ko')) return 'ko_KR';
        return 'en_US';
    };

    useEffect(() => {
        const vditorDom = document.getElementById('vditor');
        if (!vditorDom) return

        const vditor = new Vditor("vditor", {
            value,
            cdn: location.origin + __APP_ENV__.BASE_URL + '/vditor',
            toolbar: [],
            cache: {
                enable: false
            },
            height: boxRef.current.clientHeight,
            mode: "wysiwyg",
            placeholder: "",
            lang: mapLangToVditor(currentLang),
            after() {
                setRenderingCompleted(true);
                veditorRef.current = vditor;
                scrollBoxRef.current = vditorDom.querySelector('.vditor-reset');
                // 拦截粘贴
                const editorElement = vditor.vditor[vditor.vditor.currentMode].element
                getMarkdownPaste(editorElement, (text) => {
                    const value = replaceBracesToMarkers(text, nameToValueRef.current)
                    const name = replaceMarkersToBraces(value, valueToNameRef.current, nameToValueRef.current)
                    // inset方法可及时渲染；update可覆盖选区； 只有包含变量使用inset，尽量使用update
                    const regex = /\{\{[@#](.*?)[@#]\}\}/g;
                    regex.test(name) ? vditor.insertValue(name) : vditor.updateValue(name)
                })
            },
            input: (val) => onChange(replaceBracesToMarkers(val, nameToValueRef.current)),
            hint: {
                parse: false, // 必须
                placeholder: {
                    delay: 2000,
                    text: localize('com_agent_input_knowledge_tool'),
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
            offPaste: true
        });

        return () => {
            veditorRef.current?.destroy();
            veditorRef.current = null
        };
    }, [currentLang]);

    useEffect(() => {
        // 用户手动输入不再更新setValue markdown
        if (!inputSop && (value === '' || value)) {
            // 回显值
            veditorRef.current?.setValue(replaceMarkersToBraces(value, valueToNameRef.current, nameToValueRef.current))
        }

        if (scrollBoxRef.current && linsight.status !== SopStatus.SopGenerated) {
            scrollBoxRef.current.scrollTop = scrollBoxRef.current.scrollHeight
        }
    }, [value, linsight.status, inputSop, RenderingCompleted])

    // 开启/禁用
    useEffect(() => {
        if (disable) {
            veditorRef.current?.disabled()
        } else {
            veditorRef.current?.enable()
        }
    }, [disable, RenderingCompleted])

    // 暴露方法给父组件
    useImperativeHandle(ref, () => ({
        getValue: () => {
            return replaceBracesToMarkers(veditorRef.current?.getValue(), nameToValueRef.current)
        },
    }));

    const [menuOpen, setMenuOpen] = useState(false);
    const [menuPosition, setMenuPosition] = useState({ top: 0, left: 0 });

    console.log('toolOptions :>> ', toolOptions);

    const handleChange = (val) => {
        inserRef.current(`{{@${val.label}@}}`);
        setMenuOpen(false)
    }

    useAtTip(scrollBoxRef)

    return <div ref={boxRef} className="relative h-full">
        <div id="vditor" className="linsight-vditor border-none" />
        {/* 工具选择 */}
        <SopToolsDown
            open={menuOpen}
            parentRef={boxRef}
            position={menuPosition}
            options={toolOptions}
            onChange={handleChange}
            onClose={() => setMenuOpen(false)}
        />
        <ToolErrorTip />
    </div >;
});


export default SopMarkdown;


// 工具整合
const useSopTools = (linsight) => {
    const { id, files, file_list, tools, org_knowledge_enabled, personal_knowledge_enabled } = linsight
    const { data: bsConfig } = useGetBsConfig()
    const localize = useLocalize()

    const { data: linsightTools } = useGetLinsightToolList();
    const { data: personalTool } = useGetPersonalToolList();
    const { data: orgTools } = useGetOrgToolList();

    const nameToValueRef = useRef({});
    const valueToNameRef = useRef({});
    // 整合数据为二级树结构
    const buildTreeData = useMemo(() => {
        nameToValueRef.current = {};
        valueToNameRef.current = {};
        const tree: { label: string; value: string; desc: string; children: any[] }[] = [];

        // 1. 转换files数据
        if (files?.length > 0) {
            const fileNode: any = {
                label: localize('com_sop_upload_file'),
                value: "",
                desc: '',
                children: []
            };
            const _name = localize('com_sop_upload_file_directory');
            const _value = `${localize('com_sop_upload_file_directory')}:${bsConfig?.linsight_cache_dir}/${id?.substring(0, 8)}`;
            nameToValueRef.current[_name] = _value;
            valueToNameRef.current[_value] = _name;

            fileNode.children = [{
                label: _name,
                value: _value,
                desc: '',
            }, ...files?.map(file => {
                const name = file.file_name;
                const value = `${file.file_name}的文件储存信息:{'文件储存在语义检索库中的id':'${file.file_id}','文件储存地址':'./${decodeURIComponent(file.markdown_filename)}'}`;
                nameToValueRef.current[name] = value;
                valueToNameRef.current[value] = name;
                return {
                    label: file.file_name,
                    value: file.file_id,
                    desc: '',
                    children: []
                }
            }) || []];
            tree.push(fileNode);

            // 补充结果文件到 ref映射
            if (file_list?.length) {
                file_list.forEach(file => {
                    const name = file.file_name;
                    const value = `${file.file_name}的文件储存信息:{'文件储存在语义检索库中的id':'${file.file_id}','文件储存地址':'./${decodeURIComponent(file.markdown_filename)}'}`;
                    nameToValueRef.current[name] = value;
                    valueToNameRef.current[value] = name;
                });
            }
        }

        // 2. 转换orgTools数据
        if (org_knowledge_enabled && orgTools && orgTools.length > 0) {
            tree.push({
                label: localize('com_sop_organize_knowledge_base'),
                value: "org_knowledge_base", // 使用特殊标识避免ID冲突
                desc: '',
                children: orgTools.map(tool => {
                    const name = tool.name;
                    const value = `${tool.name}的储存信息:{'知识库储存在语义检索库中的id':'${tool.id}'}`
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
        if (personal_knowledge_enabled && personalTool && personalTool[0]) {
            tree.push({
                // label: personalTool[0].name,
                label: localize('com_sop_personal_knowledge_base'),
                value: personalTool[0].id,
                desc: '',
                children: [] // 个人知识库没有子节点
            });
            const name = personalTool[0].name;
            const value = `${personalTool[0].name}的储存信息:{'知识库储存在语义检索库中的id':'${personalTool[0].id}'}`
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
    }, [linsightTools, personalTool, orgTools, files, tools, localize]);

    console.log('整合后的树结构:', buildTreeData);
    return { nameToValueRef, valueToNameRef, buildTreeData };
};

// 滚动、resize隐藏@标记
const useAtTip = (scrollBoxRef) => {
    useEffect(() => {

        const handleHideAtDom = () => {
            const atDom = document.querySelector('#vditor-placeholder-at');
            if (atDom) {
                atDom.style.display = 'none';
            }
        };
        let resizeObserver;
        if (scrollBoxRef.current) {
            scrollBoxRef.current.addEventListener('scroll', handleHideAtDom);
            // Set up ResizeObserver for width changes
            resizeObserver = new ResizeObserver(handleHideAtDom);
            resizeObserver.observe(scrollBoxRef.current);
        }

        return () => {
            if (scrollBoxRef.current) {
                scrollBoxRef.current.removeEventListener('scroll', handleHideAtDom);
            }
            if (resizeObserver) {
                resizeObserver.disconnect();
            }
        };
    }, [scrollBoxRef.current])
}

// 自适应高度
const useAutoHeight = (boxRef) => {
    useEffect(() => {
        if (!boxRef.current) return;

        const vditorDom = document.getElementById("vditor");
        if (!vditorDom) return;

        // 监听 boxRef 的高度变化
        const resizeObserver = new ResizeObserver((entries) => {
            for (const entry of entries) {
                const { height } = entry.contentRect;
                vditorDom.style.height = `${height}px`;
            }
        });

        resizeObserver.observe(boxRef.current);

        // 组件卸载时取消监听
        return () => {
            resizeObserver.disconnect();
        };
    }, []);
}

// markdown粘贴逻辑
const getMarkdownPaste = async (editorElement, callBack) => {
    // 监听粘贴事件
    editorElement.addEventListener('paste', async (event) => {
        // 1. 阻止默认粘贴行为
        event.preventDefault();

        // 2. 获取剪贴板数据
        const clipboardData = event.clipboardData || window.clipboardData;

        // 3. 处理不同类型的数据
        let processedContent = '';

        // 情况1: 纯文本处理
        if (clipboardData.types.includes('text/plain')) {
            const text = clipboardData.getData('text/plain');
            processedContent = await processText(text); // 自定义文本处理函数
        }

        // 情况2: HTML内容处理 (如从网页复制)
        // else if (clipboardData.types.includes('text/html')) {
        //     const html = clipboardData.getData('text/html');
        //     processedContent = await processHTML(html); // 自定义HTML处理函数
        // }

        // 情况3: 图片处理
        // else if ([...clipboardData.items].some(item => item.type.includes('image'))) {
        //     processedContent = await processImage(clipboardData); // 自定义图片处理
        // }

        // 4. 插入处理后的内容
        if (processedContent) {
            // 使用 Vditor API 插入内容

            callBack(processedContent);
            // 或者直接操作 DOM (适用于复杂插入)
            // document.execCommand('insertHTML', false, processedContent);
        }
    });

    // 示例处理函数
    async function processText(text) {
        // 在这里实现你的文本处理逻辑
        return text.replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    async function processHTML(html) {
        // 示例：移除所有HTML标签只保留纯文本
        const doc = new DOMParser().parseFromString(html, 'text/html');
        return doc.body.textContent || "";
    }

    async function processImage(clipboardData) {
        // 获取图片文件
        const imageItem = [...clipboardData.items].find(item =>
            item.type.includes('image')
        );

        if (!imageItem) return '';

        const blob = imageItem.getAsFile();
        const base64 = await convertBlobToBase64(blob);

        // 返回 Markdown 图片格式
        return `![粘贴图片](${base64})`;
    }

    function convertBlobToBase64(blob) {
        return new Promise((resolve) => {
            const reader = new FileReader();
            reader.onloadend = () => resolve(reader.result);
            reader.readAsDataURL(blob);
        });
    }
}

/**
 * 正向替换：将 @标记@ 替换为 {{value}} 格式
 * @param {string} inputStr - 输入字符串
 * @param {Object} valueToNameMap - 映射对象 {id: value}
 * @returns {string} - 替换后的字符串
 */
function replaceMarkersToBraces(inputStr, valueToNameMap, nameToValueMap) {
    const regex = /@([^@\r\n]+)@/g;
    return inputStr.replace(regex, (match, id) => {
        // 检查映射中是否存在该ID
        if (Object.prototype.hasOwnProperty.call(valueToNameMap, id)) {
            return `{{@${valueToNameMap[id]}@}}`;
        }
        // 反推回原始值
        if (Object.prototype.hasOwnProperty.call(nameToValueMap, id)) {
            return `{{@${id}@}}`;
        }
        // 文件不校验
        const pattern = /([^@{}'\.]+?\.[^@{}'\s]+)的文件储存信息:\{(['"])[^'"]+\2:\s*(['"])[^'"]*\3,\s*(['"])[^'"]+\4:\s*(['"])[^'"]*\5\}/g
        const _match = pattern.exec(id);
        if (_match?.[1]) {
            // 特殊关系记录
            const name = _match[1];
            const value = id;
            valueToNameMap[value] = name;
            nameToValueMap[name] = value;

            return `{{@${_match[1]}@}}`;
        }
        // 只要包含 .md .html .csv .txt 这四种格式后缀的，都不校验
        if (/(\.md)|(\.html)|(\.csv)|(\.txt)/g.test(id.toLowerCase())) {
            return `{{@${id}@}}`;
        }

        console.warn('转换ui时未找到对应的ID  :>> ', valueToNameMap, id);
        return `{{#${id}#}}`; // 未找到时标记红色
    });
}

/**
 * 反向替换：将 {{value}} 替换为 @id@ 格式
 * @param {string} inputStr - 输入字符串
 * @param {Object} nameToValueMap - 映射对象 {value: id}
 * @returns {string} - 替换后的字符串
 */
function replaceBracesToMarkers(inputStr, nameToValueMap) {
    const regex = /\{\{[@#](.*?)[@#]\}\}/g;
    return inputStr.replace(regex, (match, value) => {
        // 检查映射中是否存在该值
        if (Object.prototype.hasOwnProperty.call(nameToValueMap, value)) {
            return `@${nameToValueMap[value]}@`;
        }
        console.warn('转换sop时未找到对应的工具  :>> ', nameToValueMap, value);
        return `@${value}@`; // 未找到时保留原始值
    });
}
