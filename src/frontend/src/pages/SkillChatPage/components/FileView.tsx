import * as pdfjsLib from 'pdfjs-dist';
import React, { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { FixedSizeList as List, areEqual } from 'react-window';

const SASS_HOST = 'https://bisheng.dataelem.com'
export const checkSassUrl = (url: string) => {
    return location.origin === SASS_HOST ? url.replace(/https?:\/\/[^\/]+/, SASS_HOST) : url;
}
interface Chunk {
    id: number
    scoreL: number
    page: number
    box: number[]
}

interface RowProps {
    index: number
    style: any
    size: number
    labels?: number[]
    pdf: any
    onLoad: (w: number) => void
}
// 绘制一页pdf
const Row = React.memo(({ index, style, size, labels, pdf, onLoad }: RowProps) => {
    const wrapRef = useRef(null);
    const txtRef = useRef(null);
    // 绘制
    const [scaleState, setScaleState] = useState(1)
    const draw = async () => {
        const page = await pdf.getPage(index + 1); // TODO cache
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

        // 渲染页面
        page.render({
            canvasContext: context,
            viewport: page.getViewport({ scale }),
            // transform
        });

        drawText(page, page.getViewport({ scale }))
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

    useEffect(() => {
        draw()
        // return () => {};
    }, [])

    return <div className="bg-[#fff] border-b-2 overflow-hidden" style={style}>
        {/* <span className="absolute">{index + 1}</span> */}
        {/* canvas  */}
        <div ref={wrapRef} className="canvasWrapper"></div>
        {/* label */}
        {labels && <svg className="absolute top-0 w-full h-full">
            {labels.map(box =>
                <rect
                    key={box[0]}
                    x={box[0] * scaleState}
                    y={box[1] * scaleState}
                    width={(box[2] - box[0]) * scaleState}
                    height={(box[3] - box[1]) * scaleState}
                    style={{ fill: 'rgba(255, 236, 61, 0.2)', strokeWidth: 1, stroke: '#ffec3d' }} />
            )}
        </svg>}
        {/* text  */}
        <div ref={txtRef} className="textLayer absolute inset-0 overflow-hidden opacity-25 origin-top-left z-20 leading-none"></div>
        {/* Row {index} */}
    </div>
}, areEqual)


export default function FileView({ data }) {
    const { t } = useTranslation()
    const paneRef = useRef(null)
    const listRef = useRef(null)
    const [boxSize, setBoxSize] = useState({ width: 0, height: 0 })
    const [loading, setLoading] = useState(false)
    // chunk
    const [currentChunk, setCurrentChunk] = useState(-1) // 选中的chunk

    const useLabels = () => {
        const [data, setData] = useState({})
        return [data, (chunk) => {
            const map = {}
            chunk.box.forEach(el => map[el.page]
                ? map[el.page].push(el.bbox)
                : (map[el.page] = [el.bbox]))
            setData(map)
        }] as const
    }
    const [pageLabels, setPagesLabels] = useLabels()
    // console.log('pageLabels :>> ', pageLabels);

    // 视口
    useEffect(() => {
        const panneDom = paneRef.current
        const resize = () => {
            if (panneDom) {
                const [width, height] = [panneDom.offsetWidth - 16, panneDom.offsetHeight - 32]
                setBoxSize({ width, height })
                const warpDom = document.getElementById('warp-pdf')
                warpDom.style.setProperty("--scale-factor", width / fileWidthRef.current + '')
            }
        }
        resize()
        window.addEventListener('resize', resize)
        return () => window.removeEventListener('resize', resize)
    }, [])

    // 加载文件
    const [pdf, setPdf] = useState(null)
    useEffect(() => {
        // loding
        setLoading(true)
        setPagesLabels({ box: [] })

        // sass环境使用sass地址
        const pdfUrl = checkSassUrl(data.fileUrl);  // '/doc.pdf';
        pdfjsLib.GlobalWorkerOptions.workerSrc = '/pdf.worker.min.js';
        pdfjsLib.getDocument(pdfUrl).promise.then((pdfDocument) => {
            setLoading(false)
            setPdf(pdfDocument)
            // 默认跳转到匹配度最高的page
            setTimeout(() => {
                setCurrentChunk(0)
                const chunk = data.chunks[0]
                setPagesLabels(chunk)
                const pageY = (chunk.box[0].page - 1) * (boxSize.width / 0.7)
                // 第一个高亮块的当页位移
                const offsetY = chunk.box[0].bbox[1] * (boxSize.width / fileWidthRef.current) - 100
                // 页码滚动位置
                listRef.current.scrollTo(pageY + offsetY);
                // listRef.current.scrollToItem(data.chunks[0].box[0].page - 1, 'start');
            }, 3000);
        })
    }, [data])

    const handleJump = (i: number, chunk: typeof data.chunks[number]) => {
        // 选中的chunk label
        setPagesLabels(chunk)
        setCurrentChunk(i)
        // listRef.current.scrollToItem(chunk.box[0].page - 1, 'start');
        // 第一个高亮块的当页位移
        const offsetY = chunk.box[0].bbox[1] * (boxSize.width / fileWidthRef.current) - 100
        // 页码滚动位置
        const pageY = (chunk.box[0].page - 1) * (boxSize.width / 0.7)
        listRef.current.scrollTo(pageY + offsetY);
    }

    const fileWidthRef = useRef(1)
    const handleLoadPage = (w: number) => {
        if (fileWidthRef.current === w) return
        const warpDom = document.getElementById('warp-pdf')
        warpDom.style.setProperty("--scale-factor", boxSize.width / w + '')
        fileWidthRef.current = w
    }

    return <div ref={paneRef} className="flex-1 bg-gray-100 rounded-md py-4 px-2 relative">
        {
            loading
                ? <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
                    <span className="loading loading-infinity loading-lg"></span>
                </div>
                : <div id="warp-pdf" className="file-view absolute">
                    <List
                        ref={listRef}
                        itemCount={pdf?.numPages || 100}
                        // A4 比例(itemSize：item的高度)
                        // 595.32 * 841.92 采用宽高比0.70约束
                        itemSize={boxSize.width / 0.7}
                        // 滚动区盒子大小
                        width={boxSize.width}
                        height={boxSize.height}
                    >
                        {/* {(props) => <div>{props.index}</div>} */}
                        {(props) => <Row {...props} pdf={pdf} size={boxSize.width} labels={pageLabels[props.index + 1]} onLoad={handleLoadPage}></Row>}
                    </List>
                </div>
        }
        <div className="absolute left-[0px] rounded-sm p-4 px-0 top-[50%] translate-y-[-50%] max-2xl:scale-75 origin-top-left">
            <p className="mb-1 text-sm font-bold text-center rounded-sm bg-[rgb(186,210,249)] text-blue-600">{t('chat.sourceTooltip')}</p>
            <div className="flex flex-col gap-2 ">
                {data.chunks.map((chunk, i) =>
                    <div key={i}
                        onClick={() => handleJump(i, chunk)}
                        className={`flag h-[38px] leading-[38px] px-6 pl-4 border-2 border-l-0 border-r-0 border-[rgba(53,126,249,.60)] bg-[rgba(255,255,255,0.2)]  text-blue-600 ${currentChunk === i && 'font-bold active'} cursor-pointer relative`}
                    >
                        <span>{chunk.score}</span>
                    </div>
                )}
            </div>
        </div>
    </div>
};
