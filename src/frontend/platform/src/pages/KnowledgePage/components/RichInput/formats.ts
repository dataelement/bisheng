import Quill from 'quill';

const BlockEmbed = Quill.import('blots/block/embed');

class FileBlot extends BlockEmbed {
  static create(value: { url: string; name: string; }) {
    console.log('create', value);
    
    const node = super.create(value) as HTMLElement;
    node.style.display = 'inline-block'; // 关键修改
    node.setAttribute('data-url', value.url);
    node.setAttribute('data-name', value.name);
    node.setAttribute('contenteditable', 'false'); // 关键属性

    node.innerHTML = `
      <a href="#" class="text-primary no-underline hover:underline px-1">${value.name}</a>
    `;
    return node;
  }

  static value(node: HTMLElement) {
    console.log('value', node);
    return {
      url: node.getAttribute('data-url'),
      name: node.getAttribute('data-name'),
    };
  }
  
  // 使 Blot 不可分割
  static formats(node) {
    return true;
  }

}

FileBlot.blotName = 'bsfile';
FileBlot.tagName = 'div';
FileBlot.className = 'ql-bsfile';

// 更安全的注册方式
const registerFileBlot = () => {
  try {
    // 检查是否已注册
    if (!Quill.imports['blots/bsfile']) {
      Quill.register({
        'blots/bsfile': FileBlot,
        'formats/bsfile': FileBlot  // 关键：注册为格式
      }, true);
    }
  } catch (error) {
    console.error('注册FileBlot失败:', error);
  }
};

export { registerFileBlot, FileBlot };