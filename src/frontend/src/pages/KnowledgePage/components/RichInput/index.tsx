import React, { useMemo, useRef, useEffect, useState } from 'react';
import ReactQuill from 'react-quill';
import 'react-quill/dist/quill.snow.css';
import './styles.css';
import CustomToolbar from './toorbar';
import { modules } from './modules';
import { registerFileBlot } from './formats';

interface RichTextEditorProps {
  value: string;
  onChange: (content: string) => void;
  placeholder?: string;
  className?: string;
}

const RichTextEditor: React.FC<RichTextEditorProps> = ({
  value,
  onChange,
  placeholder = '',
  className = '',
}) => {
  const quillRef = useRef<ReactQuill>(null);
  const [mounted, setMounted] = useState(false);

  // 确保组件挂载后再渲染Quill，避免SSR问题
  useEffect(() => {
    registerFileBlot();
    setMounted(true);
  }, []);

  const formats = [
    'header',
    'bold',
    'italic',
    'underline',
    'strike',
    'list',
    'bullet',
    'link',
    'image',
    'bsfile', // 与blotName一致
  ];

  const handleChange = (content: string) => {
    console.log('content', content);
    onChange(content);
  };

  if (!mounted) {
    return <div className={`quill-placeholder ${className}`}>{placeholder}</div>;
  }

  return (
    <div className={`rich-text-editor ${className}`}>
      <CustomToolbar />
      <div className='max-h-[100px] overflow-y-auto scrollbar-hide'>
        <ReactQuill
          ref={quillRef}
          theme="snow"
          value={value}
          onChange={handleChange}
          modules={modules}
          formats={formats}
          placeholder={placeholder}
          bounds=".rich-text-editor"
        />
      </div>
    </div>
  );
};

export default RichTextEditor;