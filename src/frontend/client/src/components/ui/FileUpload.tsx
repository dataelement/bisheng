import React, { forwardRef } from 'react';

type FileUploadProps = {
  className?: string;
  onClick?: () => void;
  children: React.ReactNode;
  handleFileChange: (event: React.ChangeEvent<HTMLInputElement>) => void;
};

const FileUpload = forwardRef<HTMLInputElement, FileUploadProps>(
  ({ children, handleFileChange }, ref) => {
    return (
      <>
        {children}
        <input
          ref={ref}
          // pdf、txt、docx、pptx、md、html、xls、xlsx、doc、ppt、png、jgp、jpeg、bmp
          accept='.pdf,.txt,.docx,.pptx,.md,.html,.xls,.xlsx,.doc,.ppt,.png,.jpg,.jpeg,.bmp'
          multiple
          type="file"
          style={{ display: 'none' }}
          onChange={handleFileChange}
        />
      </>
    );
  },
);

FileUpload.displayName = 'FileUpload';

export default FileUpload;
