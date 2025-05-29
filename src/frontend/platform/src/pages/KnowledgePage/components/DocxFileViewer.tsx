import React, { useState, useEffect, useRef } from "react";
import * as mammoth from "mammoth";
import { LoadingIcon } from "@/components/bs-icons/loading";

const DocxPreview = ({ filePath }) => {
    const [htmlContent, setHtmlContent] = useState("");
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const previewRef = useRef(null);

    useEffect(() => {
        const fetchAndConvertDocx = async () => {
            try {
                setLoading(true);
                // 1. 下载 DOCX 文件
                const response = await fetch(filePath.replace(/https?:\/\/[^\/]+/, __APP_ENV__.BASE_URL));
                if (!response.ok) throw new Error(`Failed to fetch file: ${response.status}`);

                // 2. 获取文件 ArrayBuffer
                const arrayBuffer = await response.arrayBuffer();

                // 3. 使用 Mammoth 转换为 HTML
                const result = await mammoth.convertToHtml({ arrayBuffer });

                // 4. 设置生成的 HTML
                setHtmlContent(result.value);
                setError(null);
            } catch (err) {
                setError(err.message);
                setHtmlContent(`<p class="error">Failed to load DOCX file: ${err.message}</p>`);
            } finally {
                setLoading(false);
            }
        };

        fetchAndConvertDocx();
    }, [filePath]);

    // 自定义样式（可选）
    const docxStyles = `
    .docx-wrapper {
      font-family: Arial, sans-serif;
      line-height: 1.5;
      padding: 20px;
      font-size: 14px;
    }
    .docx-wrapper p {
      margin: 0 0 1em 0;
    }
    .docx-wrapper table {
      border-collapse: collapse;
      width: 100%;
      margin: 1em 0;
    }
    .docx-wrapper table td {
      border: 1px solid #ddd;
      padding: 8px;
    }
    .error {
      color: red;
    }
  `;

    if (loading) {
        return <div className="absolute left-0 top-0 z-10 flex h-full w-full items-center justify-center bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
            <LoadingIcon />
        </div>
    }

    return (
        <div className="border rounded-lg overflow-hidden bg-white">
            {/* 注入自定义样式 */}
            <style dangerouslySetInnerHTML={{ __html: docxStyles }} />

            {/* 渲染转换后的 HTML */}
            <div
                ref={previewRef}
                className="docx-wrapper h-full p-4"
                dangerouslySetInnerHTML={{ __html: htmlContent }}
            />

            {/* 错误提示 */}
            {error && (
                <div className="p-4 bg-red-50 text-red-600">
                    Preview failed: {error}. <a href={filePath} download className="underline">Download original file</a>
                </div>
            )}
        </div>
    );
};

export default DocxPreview;