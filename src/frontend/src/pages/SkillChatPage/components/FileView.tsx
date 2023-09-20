import { ChevronDownSquare, ChevronUpSquare, Bookmark } from "lucide-react";
import React, { useEffect, useMemo, useRef, useState } from "react";
import { FixedSizeList as List, areEqual } from 'react-window';
import { Button } from "../../../components/ui/button";
import * as pdfjsLib from 'pdfjs-dist';

interface Chunk {
    id: number
    scoreL: number
    page: number
    box: number[]
}


const Row = React.memo(({ index, style, viewScale, chunks, pdf }: { index: number, style: any, viewScale: number, chunks: Chunk[], pdf: any }) => {
    const wrapRef = useRef(null);
    const txtRef = useRef(null);
    // 绘制
    const draw = async () => {
        console.log('window.devicePixelRatio :>> ', window.devicePixelRatio);
        const page = await pdf.getPage(index + 1); // TODO cache
        const scale = 1;
        const viewport = page.getViewport({ scale: scale * viewScale });
        const canvas = document.createElement('canvas')
        const context = canvas.getContext('2d')
        const outputScale = window.devicePixelRatio || 1;
        canvas.width = Math.floor(viewport.width * outputScale);
        canvas.height = Math.floor(viewport.height * outputScale);
        canvas.style.width = Math.floor(viewport.width) + "px";
        canvas.style.height = Math.floor(viewport.height) + "px";
        wrapRef.current.append(canvas)
        const transform = outputScale !== 1 ? [outputScale, 0, 0, outputScale,
            0, 0
        ] : null;

        // 渲染页面
        page.render({
            canvasContext: context,
            viewport: viewport,
            transform
        });

        drawText(page, viewport)
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
        console.log('draw pdf :>> ', index);
        draw()
        // return () => {};
    })

    return <div className="bg-[#fff] border-b-2" style={style}>
        {/* canvas  */}
        <div ref={wrapRef} className="canvasWrapper"></div>
        {/* label */}
        {chunks && <svg className=" absolute top-0">
            {chunks.map(chunk =>
                <rect
                    key={chunk.id}
                    x={chunk.box[0] / viewScale}
                    y={chunk.box[1] / viewScale}
                    width={(chunk.box[2] - chunk.box[0]) / viewScale}
                    height={(chunk.box[4] - chunk.box[1]) / viewScale}
                    style={{ fill: 'rgba(255, 236, 61, 0.2)', strokeWidth: 1, stroke: '#ffec3d' }} />
            )}
        </svg>}
        {/* text  */}
        <div ref={txtRef} className="textLayer absolute inset-0 overflow-hidden opacity-25 origin-top-left z-20 leading-none"></div>
        {/* Row {index} */}
    </div>
}, areEqual)


export default function FileView() {
    const s618 = 618
    const paneRef = useRef(null)
    const listRef = useRef(null)
    const [boxSize, setBoxSize] = useState({ width: 0, height: 0 })
    // chunk
    const [currentChunk, setCurrentChunk] = useState(0)
    const [chunks, setChunks] = useState([
        { id: 1, score: 0.8, page: 3, box: [0, 0, 100, 0, 100, 50, 0, 50] },
        { id: 2, score: 0.5, page: 1, box: [0, 0, 100, 0, 100, 50, 0, 50] },
        { id: 3, score: 0.4, page: 1, box: [10, 0, 100, 0, 100, 50, 10, 50] },
        { id: 4, score: 0.4, page: 50, box: [10, 10, 100, 10, 100, 50, 10, 50] }
    ])
    const pageChunks = useMemo(() => {
        const map = {}
        chunks.forEach(el => {
            if (map[el.page]) {
                map[el.page].push(el)
            } else {
                map[el.page] = [el]
            }
        })
        return map
    }, [chunks])

    // 视口
    useEffect(() => {
        const panneDom = paneRef.current
        const resize = () => {
            if (panneDom) {
                setBoxSize({ width: panneDom.offsetWidth, height: panneDom.offsetHeight })
                const warpDom = document.getElementById('warp-pdf')
                warpDom.style.setProperty("--scale-factor", panneDom.offsetWidth / s618 + '')
            }
        }
        resize()
        window.addEventListener('resize', resize)
        return () => window.removeEventListener('resize', resize)
    }, [])

    // 下载文件
    const [pdf, setPdf] = useState(null)
    useEffect(() => {
        const pdfUrl = '/doc.pdf';
        pdfjsLib.GlobalWorkerOptions.workerSrc = '/pdf.worker.min.js';
        pdfjsLib.getDocument(pdfUrl).promise.then((pdfDocument) => {
            setPdf(pdfDocument)
        })
    }, [])

    const handleJump = (chunk: typeof chunks[number]) => {
        setCurrentChunk(chunk.id)
        listRef.current.scrollToItem(chunk.page - 1, 'start');
    }

    return <div ref={paneRef} className="flex-1 bg-gray-100 rounded-md py-4 px-2 relative">
        <div id="warp-pdf" className="file-view absolute">
            <List
                ref={listRef}
                itemCount={pdf?.numPages || 0}
                // A4 比例
                itemSize={boxSize.width / 1240 * 1754}
                width={boxSize.width - 16}
                height={boxSize.height - 32}
            >
                {(props) => <Row {...props} pdf={pdf} viewScale={boxSize.width / s618} chunks={pageChunks[props.index + 1]}></Row>}
            </List>
        </div>
        <div className="absolute right-6 top-6 flex flex-col gap-2">
            {chunks.map(chunk =>
                <div key={chunk.id}
                    onClick={() => handleJump(chunk)}
                    className={`flex gap-1 items-center justify-end ${currentChunk === chunk.id && 'text-blue-600'} cursor-pointer`}
                >
                    <Bookmark size={18} className={currentChunk === chunk.id ? 'block' : 'hidden'}></Bookmark>
                    <span>{chunk.score}</span>
                </div>
            )}
        </div>
    </div>
};
