import { Quill } from "react-quill";
import { uploadFile } from '@/util/utils'
import { Delta } from "quill";

export const modules = {
  toolbar: {
    container: '#toolbar',
    handlers: {
      bsfile: function (this: any) {
        console.log('handlersfile');
        
        const fileInput = document.createElement('input');
        fileInput.setAttribute('type', 'file');
        fileInput.setAttribute('accept', '*');
        fileInput.style.display = 'none';
        fileInput.click();
        const that = this;
        fileInput.onchange = async () => {
          if (fileInput.files && fileInput.files[0]) {
            const file = fileInput.files[0];
            const quill = that.quill;
            const range = quill.getSelection(true);
            
            // 插入临时占位文本
            const placeholder = '上传中...';
            quill.insertText(range.index, placeholder, { color: '#999' });
            quill.disable();
            try {
              const result = await upload(file);
              // 删除占位文本
              quill.deleteText(range.index, placeholder.length);
              quill.enable();
              console.log('Before insert:', range.index, quill.getContents(), {
                url: result.url,
                name: file.name,
              });
              // 确保使用正确的blot名称
              quill.insertEmbed(
                range.index,
                'bsfile', // 必须与blotName一致
                {
                  url: result.url,
                  name: file.name,
                },
                'user'
              );
              // 插入换行符
              // quill.insertText(range.index + 1, '\n', 'silent');
              // quill.setSelection(range.index + 2, 0, 'silent');
            } catch (error) {
              console.error('上传失败:', error);
              quill.deleteText(range.index, placeholder.length);
              quill.insertText(range.index, '上传失败', { color: 'red' });
            } finally {
              quill.enable();
            }
          }
        };
      },
    },
  },
  clipboard: {
    matchVisual: false,
  },
};

// 文件上传函数示例
async function upload(file: File): Promise<{ url: string }> {
  console.log('上传图片:', file.name);
  const res = await uploadFile({ url: __APP_ENV__.BASE_URL + '/api/v1/knowledge/upload', file });
  if (res) { 
    return {
      url: res.data?.file_path
    }
  } else {
    throw new Error('上传失败');
  }
}