import React, { useState, useRef, useCallback } from 'react';
import ReactQuill from 'react-quill';
import 'react-quill/dist/quill.snow.css';
import { uploadFile } from '@/util/utils'

const RichTextEditor = ({ value, onChange, className = '', placeholder = '', url = '' }) => {
  const quillRef = useRef(null);
  
  // 图片上传处理函数
  const imageHandler = useCallback(() => {
    const input = document.createElement('input');
    input.setAttribute('type', 'file');
    input.setAttribute('accept', 'image/*');
    input.click();
    
    input.onchange = async () => {
      const file = input.files[0];
      if (!file) return;
      
      try {
        // 这里调用你的图片上传函数
        const imageUrl = await upload(url, file);
        
        const quill = quillRef.current.getEditor();
        const range = quill.getSelection();
        quill.insertEmbed(range.index, 'image', imageUrl);
        quill.setSelection(range.index + 1);
      } catch (error) {
        console.error('图片上传失败:', error);
      }
    };
  }, []);

  // 文件上传处理函数
  const fileHandler = useCallback(() => {
    const input = document.createElement('input');
    input.setAttribute('type', 'file');
    input.click();
    
    input.onchange = async () => {
      const file = input.files[0];
      if (!file) return;
      
      try {
        // 这里调用你的文件上传函数
        const fileUrl = await upload(url, file);
        
        const quill = quillRef.current.getEditor();
        const range = quill.getSelection();
        
        // 创建文件链接
        quill.clipboard.dangerouslyPasteHTML(
          range.index,
          `<a href="${fileUrl}" target="_blank" rel="noopener noreferrer">${file.name}</a>`
        );
        quill.setSelection(range.index + 1);
      } catch (error) {
        console.error('文件上传失败:', error);
      }
    };
  }, []);

  // 编辑器模块配置
  const modules = {
    toolbar: {
      container: [
        [{ 'header': [1, 2, 3, false] }],
        ['bold', 'italic', 'underline', 'strike'],
        [{ 'color': [] }, { 'background': [] }],
        [{ 'list': 'ordered' }, { 'list': 'bullet' }],
        ['link', 'image', 'file'],
        ['clean']
      ],
      handlers: {
        image: imageHandler,
        file: fileHandler
      }
    },
    clipboard: {
      matchVisual: false,
    }
  };

  // 编辑器格式配置
  // const formats = [
  //   'header',
  //   'bold', 'italic', 'underline', 'strike',
  //   'color', 'background',
  //   'list', 'bullet',
  //   'link', 'image', 'file'
  // ];

  // 编辑器格式配置
  const formats = [
    'header',
    'bold', 'italic', 'underline', 'strike',
    'color', 'background',
    'list', 'bullet',
    'link', 'image', 'file'
  ];

  return (
    <div className="rich-text-editor">
      <ReactQuill
        ref={quillRef}
        theme="snow"
        value={value}
        onChange={onChange}
        modules={modules}
        formats={formats}
        placeholder={placeholder}
      />
    </div>
  );
};

// 示例上传函数 - 你需要根据实际需求实现这些函数
async function upload(url, file) {
  // 实现你的图片上传逻辑
  // 返回图片URL
  console.log('上传图片:', file.name);
  const res = await uploadFile({ url, file });
  if (res) { 
    return res.file_path;
  } else {
    return '';
  }
}

// async function uploadFile(file) {
//   // 实现你的文件上传逻辑
//   // 返回文件URL
//   console.log('上传文件:', file.name);
//   return 'https://example.com/path/to/file.pdf';
// }

export default RichTextEditor;