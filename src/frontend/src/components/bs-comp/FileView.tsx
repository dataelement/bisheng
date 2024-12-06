import throttle from 'lodash-es/throttle';
import * as pdfjsLib from 'pdfjs-dist';
import React, { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { FixedSizeList as List, areEqual } from 'react-window';
import { LoadingIcon } from '../bs-icons/loading';

// A4 比例(itemSize：item的高度)
// 595.32 * 841.92 采用宽高比0.70约束
let pageScale = 0.7
let pdfPageCache = {}

interface RowProps {
    drawfont: boolean
    index: number
    style: any
    size: number
    labels?: { id: string, label: number[], active: boolean }[]
    pdf: any
    onLoad: (w: number) => void
    onSelectLabel: (data: { id: string, active: boolean }) => void
}
// 绘制一页pdf
const Row = React.memo(({ drawfont, index, style, size, labels, pdf, onLoad, onSelectLabel }: RowProps) => {
    const wrapRef = useRef(null);
    const txtRef = useRef(null);
    const annotRef = useRef(null);
    // 绘制
    const [scaleState, setScaleState] = useState(1)
    const draw = async () => {
        const page = pdfPageCache[index + 1] || await pdf.getPage(index + 1); // TODO cache
        pdfPageCache[index + 1] = page
        const viewport = page.getViewport({ scale: 1 });
        const scale = size / viewport.width;
        setScaleState(scale)
        const canvas = document.createElement('canvas')
        const context = canvas.getContext('2d')
        const outputScale = window.devicePixelRatio || 1;
        canvas.width = Math.floor(viewport.width * scale);
        canvas.height = Math.floor(viewport.height * scale);
        canvas.style.width = Math.floor(viewport.width * scale) + "px";
        canvas.style.height = Math.floor(viewport.height * scale) + "px";
        wrapRef.current.append(canvas)
        const transform = outputScale !== 1 ? [outputScale, 0, 0, outputScale,
            0, 0
        ] : null;

        onLoad?.(viewport.width)

        // 渲染批注层
        await renderAnnotations(page, scale);
        // 渲染页面
        page.render({
            canvasContext: context,
            viewport: page.getViewport({ scale }),
            // transform
        });
        // 渲染文本层（如果需要）
        { drawfont && drawText(page, page.getViewport({ scale })) }
    }

    const drawText = async (page, viewport) => {
        page.getTextContent().then(function (textContent) {
            return pdfjsLib.renderTextLayer({
                textContentSource: textContent,
                container: txtRef.current,
                viewport: viewport,
                textDivs: []
            });
        })
    }

    const renderAnnotations = async (page, scale) => {
        // 创建注释层实例
        // const annotationLayer = new pdfjsLib.AnnotationLayer({
        //     div: annotRef.current,
        //     accessibilityManager: null,
        //     annotationCanvasMap: new Map(),
        //     l10n: {
        //         async translate(element: HTMLElement) {
        //             return Promise.resolve();
        //         },
        //         async get(key: string, args?: any) {
        //             return Promise.resolve(key);
        //         }
        //     },
        //     page,
        //     viewport
        // });
        // console.log('viewport :>> ', viewport);

        page.getAnnotations().then((annotations) => {
            const viewport = page.getViewport({ scale: 1 });
            // 自定义方式处理批注
            annotations.forEach(annotation => {
                if (annotation.subtype === 'FreeText') {
                    const { richText, rect } = annotation
                    const rootHtml = createElementFromJSON(richText.html);
                    rootHtml.style.position = 'absolute';
                    rootHtml.style.left = `${rect[0] * scale}px`;
                    rootHtml.style.top = `${(viewport.height - rect[3]) * scale - 4}px`;
                    // rootHtml.style.width = `${rect[2] * scale}px`;
                    // rootHtml.style.height = `${rect[3] * scale}px`;
                    rootHtml.style.transform = `scale(${viewport.scale})`;
                    annotRef.current.appendChild(rootHtml);
                }
            });
            // annotationLayer.render({
            //     viewport,
            //     div: annotRef.current,
            //     annotations,
            //     page,
            //     renderForms: true,
            //     linkService: null,  // 根据需要提供链接服务
            //     downloadManager: null,  // 下载管理
            // }).then(() => {
            //     console.log('Annotation layer rendered.', annotations);
            // });
        })
    };

    useEffect(() => {
        draw()
        // return () => {};
    }, [])

    // 去重
    const bboxMap = {}
    const areEqualFn = (bbox) => {
        if (bboxMap[bbox.join('-')]) {
            return true
        } else {
            bboxMap[bbox.join('-')] = true
            return false
        }
    }

    return <div className="bg-[#fff] border-b-2 overflow-hidden" style={style}>
        {/* <span className="absolute">{index + 1}</span> */}
        {/* canvas  */}
        <div ref={wrapRef} className="canvasWrapper"></div>
        {/* label */}
        {labels && <svg className="absolute top-0 w-full h-full z-30">
            {labels.map(box =>
                !areEqualFn(box.label) && <rect
                    key={box.id}
                    x={box.label[0] * scaleState}
                    y={box.label[1] * scaleState}
                    width={(box.label[2] - box.label[0]) * scaleState}
                    height={(box.label[3] - box.label[1]) * scaleState}
                    style={box.active ?
                        { fill: 'rgba(255, 236, 61, 0.2)', strokeWidth: 1, stroke: '#ffec3d', cursor: 'pointer' }
                        : { fill: 'transparent', strokeWidth: 1, stroke: '#666', strokeDasharray: 4, cursor: 'pointer' }}
                    onClick={() => onSelectLabel({ id: box.id, active: !box.active })}
                />
            )}
        </svg>}
        {/* text  */}
        <div ref={txtRef} className="textLayer absolute inset-0 overflow-hidden opacity-25 origin-top-left z-20 leading-none"></div>
        {/* annotaions */}
        <div ref={annotRef} className='absolute inset-0 overflow-hidden origin-top-left z-20'></div>
    </div>
}, areEqual)

// 拖拽面板
const DragPanne = ({ onMouseEnd }) => {
    const [isDragging, setIsDragging] = useState(false);
    const [startPos, setStartPos] = useState({ x: 0, y: 0 });
    const [currentPos, setCurrentPos] = useState({ x: 0, y: 0 });
    // const [isShiftPressed, setIsShiftPressed] = useState(false);
    const boxRef = useRef(null);

    useEffect(() => {
        const handleMouseDown = (e) => {
            const rect = boxRef.current.getBoundingClientRect();
            setIsDragging(true);
            setStartPos({ x: e.clientX - rect.left, y: e.clientY - rect.top });
            setCurrentPos({ x: e.clientX - rect.left, y: e.clientY - rect.top });
        };

        const handleMouseMove = (e) => {
            if (isDragging) {
                const rect = boxRef.current.getBoundingClientRect();
                setCurrentPos({ x: e.clientX - rect.left, y: e.clientY - rect.top });
            }
        };

        const handleMouseUp = () => {
            if (isDragging) {
                setIsDragging(false);
                onMouseEnd(startPos, currentPos)
                // console.log('Selection coordinates:', {
                //     topLeft: startPos,
                //     bottomRight: currentPos,
                // });
            }
        };

        window.addEventListener('mousedown', handleMouseDown);
        window.addEventListener('mousemove', handleMouseMove);
        window.addEventListener('mouseup', handleMouseUp);

        return () => {
            window.removeEventListener('mousedown', handleMouseDown);
            window.removeEventListener('mousemove', handleMouseMove);
            window.removeEventListener('mouseup', handleMouseUp);
        };
    }, [isDragging, startPos, currentPos, onMouseEnd]);

    return (
        <div
            ref={boxRef}
            className="absolute inset-x-2 inset-y-4 overflow-hidden z-10"
            style={{ pointerEvents: 'none' }}
        >
            {isDragging && (
                <div
                    className="absolute border-2 border-blue-500 bg-blue-100 bg-opacity-25"
                    style={{
                        opacity: Math.abs(currentPos.x - startPos.x) + Math.abs(currentPos.y - startPos.y) > 2 ? 1 : 0,
                        left: Math.min(startPos.x, currentPos.x),
                        top: Math.min(startPos.y, currentPos.y),
                        width: Math.abs(currentPos.x - startPos.x),
                        height: Math.abs(currentPos.y - startPos.y),
                    }}
                />
            )}
        </div>
    );
};
export default function FileView({
    drawfont = false,
    select = false,
    scrollTo,
    fileUrl,
    labels,
    onPageChange = (offset, h, paperSize, scale) => { },
    onSelectLabel = () => { }
}) {
    const { t } = useTranslation()
    const paneRef = useRef(null)
    const listRef = useRef(null)
    const [boxSize, setBoxSize] = useState({ width: 0, height: 0 })
    const [loading, setLoading] = useState(false)

    // 视口
    useEffect(() => {
        const panneDom = paneRef.current;

        const throttledResizeHandler = throttle(entries => {
            if (panneDom) {
                for (let entry of entries) {
                    const [width, height] = [entry.contentRect.width, entry.contentRect.height];
                    setBoxSize({ width, height });
                    const warpDom = document.getElementById('warp-pdf');
                    warpDom.style.setProperty("--scale-factor", width / fileWidthRef.current + '');
                }
            }
        }, 300);

        const resizeObserver = new ResizeObserver(throttledResizeHandler);

        if (panneDom) {
            resizeObserver.observe(panneDom);
        }

        return () => resizeObserver.unobserve(panneDom)
    }, []);
    // 加载文件
    const [pdf, setPdf] = useState(null)
    useEffect(() => {
        // loding
        setLoading(true)

        // sass环境使用sass地址
        const pdfUrl = fileUrl.replace(/https?:\/\/[^\/]+/, __APP_ENV__.BASE_URL);  // '/doc.pdf';
        pdfjsLib.GlobalWorkerOptions.workerSrc = __APP_ENV__.BASE_URL + '/pdf.worker.min.js';
        pdfjsLib.getDocument(pdfUrl).promise.then(async (pdfDocument) => {
            pdfPageCache = {}
            const page = pdfPageCache[1] || await pdfDocument.getPage(1);
            pdfPageCache[1] = page

            const viewport = page.getViewport({ scale: 1 });
            // 计算是否A4纸
            pageScale = Math.min(pageScale, viewport.width / viewport.height)
            setPdf(pdfDocument)
            setLoading(false)
        })
    }, [fileUrl])

    const scrollToFunc = (() => {
        const pageY = (scrollTo[0] - 1) * (boxSize.width / pageScale)
        const offsetY = scrollTo[1] * (boxSize.width / fileWidthRef.current) - 100
        listRef.current.scrollTo(pageY + offsetY);
    })
    useEffect(() => {
        listRef.current && scrollToFunc()
    }, [scrollTo])

    const fileWidthRef = useRef(1)
    const loadedRef = useRef(false)
    const handleLoadPage = (w: number) => {
        // 文档宽度变化时 初始化样式、宽度、定位等信息
        if (loadedRef.current) return
        // if (Math.abs(fileWidthRef.current - w) < 1) return
        const warpDom = document.getElementById('warp-pdf')
        warpDom.style.setProperty("--scale-factor", boxSize.width / w + '')
        fileWidthRef.current = w
        loadedRef.current = true
        scrollToFunc()
    }

    const scrollOffsetRef = useRef(0)
    const hanleDragSelectLabel = useCallback((start, end) => {
        let { x, y } = start
        let { x: x1, y: y1 } = end
        const scale = fileWidthRef.current / boxSize.width
        const scroll = scrollOffsetRef.current
        x *= scale
        y = (y + scroll) * scale
        x1 *= scale
        y1 = (y1 + scroll) * scale

        const selects = []
        Object.keys(labels).forEach(key => {
            const pagelabels = labels[key]
            pagelabels.forEach(item => {
                const [sx, sy, ex, ey] = item.label
                const pageH = (key - 1) * (boxSize.width / pageScale * scale)
                if (x <= sx && y <= sy + pageH && x1 >= ex && y1 >= ey + pageH) {
                    console.log('item.id :>> ', item.id);
                    selects.push({ id: item.id, active: !item.active })
                }
            })
        })
        selects.length && onSelectLabel(selects)
    }, [boxSize, labels])

    const handleScroll = ({ scrollOffset }) => {
        scrollOffsetRef.current = scrollOffset
        onPageChange?.(scrollOffset, boxSize.height, boxSize.width / pageScale, fileWidthRef.current / boxSize.width)
        // console.log('object :>> ', scrollOffset, boxSize.height, boxSize.width / 0.7);
    }

    const itemRenderer = useCallback((props) => <Row
        {...props}
        key={props.index}
        drawfont={drawfont}
        pdf={pdf}
        size={boxSize.width}
        labels={labels[props.index + 1]}
        onLoad={handleLoadPage}
        onSelectLabel={val => select && onSelectLabel([val])}
    ></Row>, [pdf, drawfont, select, labels, boxSize]);

    return <div ref={paneRef} className="flex-1 h-full bg-gray-100 rounded-md py-4 px-2 relative"
        onContextMenu={(e) => e.preventDefault()}
    >
        {
            loading
                ? <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
                    <LoadingIcon />
                </div>
                : <div id="warp-pdf" className="file-view absolute">
                    <List
                        ref={listRef}
                        itemCount={pdf?.numPages || 100}
                        itemSize={boxSize.width / pageScale}
                        // 滚动区盒子大小
                        width={boxSize.width}
                        height={boxSize.height}
                        onScroll={handleScroll}
                    >
                        {itemRenderer}
                    </List>
                </div>
        }
        {select && <DragPanne onMouseEnd={hanleDragSelectLabel} />}
    </div>
};


const SASS_HOST = 'https://bisheng.dataelem.com'
export const checkSassUrl = (url: string) => {
    return url.replace(/https?:\/\/[^\/]+/, __APP_ENV__.BASE_URL)
    // location.origin === SASS_HOST ? url.replace(/https?:\/\/[^\/]+/, '') : url;
}


/**
 * 根据给定的 JSON 结构创建 HTML 元素
 * @param {Object} node - JSON 节点
 * @returns {HTMLElement} - 创建的 HTML 元素
 */
function createElementFromJSON(node) {
    if (!node || !node.name) return null;

    // 创建元素
    const element = document.createElement(node.name);

    // 设置属性
    if (node.attributes) {
        for (const [attr, value] of Object.entries(node.attributes)) {
            if (attr === 'style' && typeof value === 'object') {
                for (const [styleName, styleValue] of Object.entries(value)) {
                    // 将驼峰式属性名转换为CSS属性名
                    const cssProperty = styleName.replace(/([A-Z])/g, '-$1').toLowerCase();
                    element.style[cssProperty] = styleValue;
                }
            } else if (attr === 'class' && Array.isArray(value)) {
                element.classList.add(...value);
            } else if (attr !== 'value') { // 确保 'value' 不是一个属性
                if (value !== undefined && value !== null) { // 避免设置 undefined 或 null
                    element.setAttribute(attr, value);
                }
            }
        }
    }

    // 添加子元素或文本内容
    if (node.children && Array.isArray(node.children)) {
        node.children.forEach(child => {
            const childElement = createElementFromJSON(child);
            if (childElement) {
                element.appendChild(childElement);
            }
        });
    }

    // 如果存在文本值，将其作为文本节点添加
    if (node.value && typeof node.value === 'string') {
        const textNode = document.createTextNode(node.value);
        element.appendChild(textNode);
    }

    return element;
}