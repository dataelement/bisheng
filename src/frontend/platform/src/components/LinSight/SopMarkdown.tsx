import { getLinsightTools, getPersonalKnowledgeInfo, readFileLibDatabase } from "@/controllers/API";
import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import { useQuery } from "react-query";
import Vditor from "vditor";
import "vditor/dist/index.css";
import SopToolsDown from "./SopToolsDown";
import { useTranslation } from "react-i18next";

// Error tool tooltip
const ToolErrorTip = () => {
    const [tooltipState, setTooltipState] = useState({
        show: false,
        message: 'Error variable',
        position: { left: 0, top: 0 }
    });
    const currentElementRef = useRef<HTMLElement | null>(null);
    const tooltipRef = useRef<HTMLDivElement>(null);

    // Handle mouseover event
    const handleMouseOver = (e: MouseEvent) => {
        const target = (e.target as HTMLElement).closest?.('.linsi-error');
        if (!(target instanceof HTMLElement)) return;

        currentElementRef.current = target;
        const rect = target.getBoundingClientRect();
        setTooltipState({
            show: true,
            message: '⚠️ Tool or resource not found, please re-select',
            position: {
                left: rect.left + rect.width / 2,
                top: rect.top - 4
            }
        });
    };

    // Handle mouseout event
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

    // Handle scroll event
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
        const container = document.getElementById('sop-vditor');
        if (!container) return;

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
    defaultValue: string,
    onChange?: any;
    disabled?: boolean;
    tools?: any;
    className?: string;
    height?: string;
}

interface MarkdownRef {
    getValue: () => string;
}

const SopMarkdown = forwardRef<MarkdownRef, MarkdownProps>((props, ref) => {
    const { value, tools, height = 'h-[calc(100vh-420px)]', defaultValue, disabled = false, onChange, className } = props;

    const veditorRef = useRef<any>(null);
    const inserRef = useRef<any>(null);
    const boxRef = useRef<any>(null);
    const scrollBoxRef = useRef<any>(null);

    useAutoHeight(boxRef);

    const { nameToValueRef, valueToNameRef, buildTreeData: toolOptions } = useSopTools(tools)
    const [RenderingCompleted, setRenderingCompleted] = useState(false);

    useEffect(() => {
        const vditorDom = document.getElementById('sop-vditor');
        if (!vditorDom) return;

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
                setRenderingCompleted(true);
                veditorRef.current = vditor;
                scrollBoxRef.current = vditorDom.querySelector('.vditor-reset');
                // Intercept paste
                const editorElement = vditor.vditor[vditor.vditor.currentMode].element;
                getMarkdownPaste(editorElement, (text) => {
                    const value = replaceBracesToMarkers(text, nameToValueRef.current);
                    const name = replaceMarkersToBraces(value, valueToNameRef.current, nameToValueRef.current);
                    vditor.insertValue(name);
                })
                // Disable
                disabled ? vditor.disabled() : vditor.enable();
            },
            input: (val) => onChange(replaceBracesToMarkers(val, nameToValueRef.current)),
            hint: {
                parse: false, // Must
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
            offPaste: true
        });

        return () => {
            veditorRef.current?.destroy();
            veditorRef.current = null;
        };
    }, []);

    useEffect(() => {
        // Sync user input value to markdown
        if (defaultValue === '' || defaultValue) {
            // Show value
            veditorRef.current?.setValue(replaceMarkersToBraces(defaultValue, valueToNameRef.current, nameToValueRef.current))
        }
    }, [RenderingCompleted])

    // Expose methods to the parent component
    useImperativeHandle(ref, () => ({
        getValue: () => {
            return replaceBracesToMarkers(veditorRef.current?.getValue(), nameToValueRef.current)
        },
        setValue: (val) => {
            veditorRef.current && veditorRef.current?.setValue(replaceMarkersToBraces(val, valueToNameRef.current, nameToValueRef.current))
        }
    }));

    const [menuOpen, setMenuOpen] = useState(false);
    const [menuPosition, setMenuPosition] = useState({ top: 0, left: 0 });

    const handleChange = (val) => {
        inserRef.current(`{{@${val.label}@}}`);
        setMenuOpen(false)
    }

    useAtTip(scrollBoxRef);

    return <div ref={boxRef} className={"relative border rounded-md bg-[#fff] " + height}>
        <div id="sop-vditor" className="linsight-vditor rounded-md border-none" />
        {/* Tool selection */}
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


// Tool integration
const useSopTools = (tools) => {
    const nameToValueRef = useRef({});
    const valueToNameRef = useRef({});
    const { t } = useTranslation('tool');

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

    // Combine data into a secondary tree structure
    const buildTreeData = useMemo(() => {
        const tree: { label: string; value: string; desc: string; children: any[] }[] = [];

        // 1. Convert files data
        if (files && files.length > 0) {
            const fileNode = {
                label: t('uploadFile'),
                value: "",
                desc: '',
                children: []
            };
            fileNode.children = files.map(file => {
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
            });
            tree.push(fileNode);
        }

        // 2. Convert orgTools data
        if (orgTools && orgTools.length > 0) {
            tree.push({
                label: t('organizeKnowledgeBase'),
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

        // 3. Convert PersonalTool data (single object to array)
        if (personalTool && personalTool[0]) {
            tree.push({
                label: t(personalTool[0].name),
                value: personalTool[0].id,
                desc: '',
                children: [] // Personal knowledge base has no children
            });
            const name = t(personalTool[0].name);
            const value = `${personalTool[0].name}的储存信息:{'知识库储存在语义检索库中的id':'${personalTool[0].id}'}`
            nameToValueRef.current[name] = value;
            valueToNameRef.current[value] = name;
        }

        // 4. Convert linsightTools data
        if (linsightTools && linsightTools.length > 0) {
            linsightTools.forEach(toolGroup => {
                tree.push({
                    label: t(toolGroup.name),
                    value: toolGroup.id,
                    desc: t(toolGroup.name + 'desc'),
                    children: (toolGroup.children || []).map(child => {
                        const name = t(child.name);
                        const value = `${child.tool_key}`
                        nameToValueRef.current[name] = value;
                        valueToNameRef.current[value] = name;
                        return {
                            label: name,
                            value: child.tool_key,
                            desc: t(child.name + 'desc'),
                            children: [] // No children for second-level nodes
                        }
                    })
                });
            });
        }
        // 5. Convert tools data
        if (tools && tools.length > 0) {
            tools.forEach(toolGroup => {
                const isPreset = toolGroup.is_preset === 1;
                toolGroup.children.length && tree.push({
                    label: isPreset ? t(`categories.${toolGroup.name}.name`) : toolGroup.name,
                    value: toolGroup.id,
                    desc: isPreset ? t(`categories.${toolGroup.name}.desc`) : toolGroup.description,
                    children: (toolGroup.children || []).map(child => {
                        const name = isPreset ? t(`tools.${child.tool_key}.name`) : child.name;
                        const value = `${child.tool_key}`
                        nameToValueRef.current[name] = value;
                        valueToNameRef.current[value] = name;
                        return {
                            label: name,
                            value: child.tool_key,
                            desc: isPreset ? t(`tools.${child.tool_key}.desc`) : child.desc,
                            children: []
                        }
                    })
                });
            });
        }

        return tree;
    }, [linsightTools, personalTool, orgTools, files, tools, t]);

    console.log('Combined tree structure:', buildTreeData);
    return { nameToValueRef, valueToNameRef, buildTreeData };
};

// Hide @ marker on scroll or resize
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
// Auto resize height
const useAutoHeight = (boxRef) => {
    useEffect(() => {
        if (!boxRef.current) return;

        const vditorDom = document.getElementById("sop-vditor");
        if (!vditorDom) return;

        // Listen to boxRef height changes
        const resizeObserver = new ResizeObserver((entries) => {
            for (const entry of entries) {
                const { height } = entry.contentRect;
                vditorDom.style.height = `${height}px`;
            }
        });

        resizeObserver.observe(boxRef.current);

        // Unsubscribe on component unmount
        return () => {
            resizeObserver.disconnect();
        };
    }, []);
}

// Markdown paste logic
const getMarkdownPaste = async (editorElement, callBack) => {
    // Listen to paste event
    editorElement.addEventListener('paste', async (event) => {
        // 1. Prevent default paste behavior
        event.preventDefault();

        // 2. Get clipboard data
        const clipboardData = event.clipboardData || window.clipboardData;

        // 3. Process different types of data
        let processedContent = '';

        // Case 1: Plain text processing
        if (clipboardData.types.includes('text/plain')) {
            const text = clipboardData.getData('text/plain');
            processedContent = await processText(text); // Custom text processing function
        }

        // Case 2: HTML content processing (like copied from a webpage)
        // else if (clipboardData.types.includes('text/html')) {
        //     const html = clipboardData.getData('text/html');
        //     processedContent = await processHTML(html); // Custom HTML processing function
        // }

        // Case 3: Image processing
        // else if ([...clipboardData.items].some(item => item.type.includes('image'))) {
        //     processedContent = await processImage(clipboardData); // Custom image processing
        // }

        // 4. Insert processed content
        if (processedContent) {
            // Use Vditor API to insert content
            callBack(processedContent);
            // Or directly manipulate DOM (for complex insertions)
            // document.execCommand('insertHTML', false, processedContent);
        }
    });

    // Example processing function
    async function processText(text) {
        // Implement your text processing logic here
        return text;
    }

    async function processHTML(html) {
        // Example: remove all HTML tags and keep only plain text
        const doc = new DOMParser().parseFromString(html, 'text/html');
        return doc.body.textContent || "";
    }

    async function processImage(clipboardData) {
        // Get image file
        const imageItem = [...clipboardData.items].find(item =>
            item.type.includes('image')
        );

        if (!imageItem) return '';

        const blob = imageItem.getAsFile();
        const base64 = await convertBlobToBase64(blob);

        // Return Markdown image format
        return `![Pasted Image](${base64})`;
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
 * Forward replace: Replace @mark@ with {{value}} format
 * @param {string} inputStr - Input string
 * @param {Object} valueToNameMap - Mapping object {id: value}
 * @returns {string} - Replaced string
 */
function replaceMarkersToBraces(inputStr, valueToNameMap, nameToValueMap) {
    const regex = /@([^@\r\n]+)@/g;
    return inputStr.replace(regex, (match, id) => {
        // Check if the ID exists in the mapping
        if (Object.prototype.hasOwnProperty.call(valueToNameMap, id)) {
            return `{{@${valueToNameMap[id]}@}}`;
        }
        // Reverse map to original value
        if (Object.prototype.hasOwnProperty.call(nameToValueMap, id)) {
            return `{{@${id}@}}`;
        }
        // No validation for files
        const pattern = /([^@{}'\.]+?\.[^@{}'\s]+)的文件储存信息:\{(['"])[^'"]+\2:\s*(['"])[^'"]*\3,\s*(['"])[^'"]+\4:\s*(['"])[^'"]*\5\}/g
        const _match = pattern.exec(id);
        if (_match?.[1]) {
            // Special relationship
            const name = _match[1];
            const value = id;
            valueToNameMap[value] = name;
            nameToValueMap[name] = value;

            return `{{@${_match[1]}@}}`;
        }
        // Check for file extensions .md, .html, .csv, .txt
        if (/(\.md)|(\.html)|(\.csv)|(\.txt)/g.test(id.toLowerCase())) {
            return `{{@${id}@}}`;
        }
        console.warn('ID not found during conversion  :>> ', valueToNameMap, id);
        return `{{@${id}@}}`;
    });
}

/**
 * Reverse replacement: Replace {{value}} with @id@ format
 * @param {string} inputStr - Input string
 * @param {Object} nameToValueMap - Mapping object {value: id}
 * @returns {string} - Replaced string
 */
function replaceBracesToMarkers(inputStr, nameToValueMap) {
    const regex = /\{\{[@#](.*?)[@#]\}\}/g;
    return inputStr.replace(regex, (match, value) => {
        // Check if the value exists in the mapping
        if (Object.prototype.hasOwnProperty.call(nameToValueMap, value)) {
            return `@${nameToValueMap[value]}@`;
        }
        console.warn('Tool not found during conversion  :>> ', nameToValueMap, value);
        return `@${value}@`; // If not found, keep the original value
    });
}

