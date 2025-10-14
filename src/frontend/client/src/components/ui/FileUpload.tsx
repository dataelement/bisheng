import React, { forwardRef, useMemo } from 'react';
import { File_Accept } from '~/common';

type FileUploadProps = {
  className?: string;
  onClick?: () => void;
  accept?: string;
  children: React.ReactNode;
  handleFileChange: (event: React.ChangeEvent<HTMLInputElement>) => void;
};

const FileUpload = forwardRef<HTMLInputElement, FileUploadProps>(
  ({ children, accept = '', handleFileChange }, ref) => {

    const _accept = useMemo(() => {
      return accept || File_Accept.Default
    }, [accept])

    return (
      <>
        {children}
        <input
          ref={ref}
          // pdf、txt、docx、pptx、md、html、xls、xlsx、doc、ppt、png、jgp、jpeg、bmp
          accept={_accept}
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
