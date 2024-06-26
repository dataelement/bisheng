import Skeleton from "@/components/bs-ui/skeleton";
import { CodeBlock } from "@/modals/formModal/chatMessage/codeBlock";
import { useDiffFlowStore } from "@/store/diffFlowStore";
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import rehypeMathjax from "rehype-mathjax";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";

const Cell = forwardRef((props, ref) => {

    const [value, setValue] = useState('')
    const [loading, setLoading] = useState(false)

    useImperativeHandle(ref, () => ({
        loading: () => {
            setLoading(true)
        },
        loaded: () => {
            setLoading(false)
        },
        setData: (val) => {
            setLoading(false)

            let i = 0
            const print = () => {
                const value = val.substring(0, i++)
                setValue(value)
                i < val.length && setTimeout(print, Math.floor(Math.random() * 10) + 20)
            }
            print()
        },
        getData() {
            return value
        }
    }));

    if (loading) return <Skeleton className="h-4 w-[200px]" />

    return <div>
        <ReactMarkdown
            remarkPlugins={[remarkGfm, remarkMath]}
            rehypePlugins={[rehypeMathjax]}
            linkTarget="_blank"
            className="bs-mkdown inline-block break-all max-w-full text-sm text-[#111]"
            components={{
                code: ({ node, inline, className, children, ...props }) => {
                    if (children.length) {
                        if (children[0] === "▍") {
                            return (<span className="form-modal-markdown-span"> ▍ </span>);
                        }

                        children[0] = (children[0] as string).replace("`▍`", "▍");
                    }

                    const match = /language-(\w+)/.exec(className || "");

                    return !inline ? (
                        <CodeBlock
                            key={Math.random()}
                            language={(match && match[1]) || ""}
                            value={String(children).replace(/\n$/, "")}
                            {...props}
                        />
                    ) : (
                        <code className={className} {...props}> {children} </code>
                    );
                },
            }}
        >
            {value.toString()}
        </ReactMarkdown>
    </div>
})


export default function CellWarp({ qIndex, versionId }) {
    const ref = useRef(null);
    const addCellRef = useDiffFlowStore(state => state.addCellRef);
    const removeCellRef = useDiffFlowStore(state => state.removeCellRef);

    useEffect(() => {
        const key = `${qIndex}-${versionId}`
        addCellRef(key, ref);

        // 组件卸载时删除 ref
        return () => {
            removeCellRef(key);
        };
    }, [qIndex, versionId, addCellRef, removeCellRef]);

    return <Cell ref={ref} />
};
