import React from 'react';
import FileIcon from './icons/FileIcon';

const TOOLBAR_ITEMS = [
  // [{ header: [1, 2, 3, false] }],
  ['bold', 'italic', 'underline', 'strike'],
  // [{ list: 'ordered' }, { list: 'bullet' }],
  ['image', 'bsfile'], // 添加了自定义文件按钮
  // ['clean'],
];

const CustomToolbar = () => (
  <div id="toolbar">
    {TOOLBAR_ITEMS.map((itemGroup, index) => (
      <span key={index} className="ql-formats">
        {itemGroup.map((item, itemIndex) => {
          if (typeof item === 'string') {
            if (item === 'bsfile') {
              return (
                // 修改按钮的className与blotName对应
                <button key={itemIndex} className="ql-bsfile" title="插入文件" onClick={(e) => e.preventDefault()}>
                  <FileIcon />
                </button>
              );
            }
            return <button key={itemIndex} className={`ql-${item}`} />;
          } else {
            const key = Object.keys(item)[0];
            const value = item[key];
            return (
              <select key={itemIndex} className={`ql-${key}`} defaultValue={value}>
                {Array.isArray(value)
                  ? value.map((val, valIndex) => (
                      <option key={valIndex} value={val}>
                        {val}
                      </option>
                    ))
                  : Object.entries(value).map(([optKey, optValue]) => (
                      <option key={optKey} value={optValue}>
                        {optKey}
                      </option>
                    ))}
              </select>
            );
          }
        })}
      </span>
    ))}
  </div>
);

export default CustomToolbar;