import type { ExtendedFile } from '~/common';
import { FileIcon, getFileTypebyFileName } from '~/components/ui/icon/File/fileIcon';
import type { TFile } from '~/data-provider/data-provider/src';
import { useProgress } from '~/hooks';

const FilePreview = ({
  file,
  fileType,
  className = '',
}: {
  file?: ExtendedFile | TFile;
  fileType: {
    paths: React.FC;
    fill: string;
    title: string;
  };
  className?: string;
}) => {
  const radius = 55; // Radius of the SVG circle
  const circumference = 2 * Math.PI * radius;
  const progress = useProgress(
    file?.['progress'] ?? 1,
    0.001,
    (file as ExtendedFile | undefined)?.size ?? 1,
  );

  // Calculate the offset based on the loading progress
  const offset = circumference - progress * circumference;
  const circleCSSProperties = {
    transition: 'stroke-dashoffset 0.5s linear',
  };

  return (<FileIcon loading={progress < 1} type={getFileTypebyFileName(file.filename)} />
    // <div className={cn('size-8 shrink-0 overflow-hidden rounded-lg', className)}>
    //   <FontIcon name={progress < 1 ? '' : file.filename} />
    //   <SourceIcon source={file?.source} />
    //   {progress < 1 && (
    //     <ProgressCircle
    //       circumference={circumference}
    //       offset={offset}
    //       circleCSSProperties={circleCSSProperties}
    //     />
    //   )}
    // </div>
  );
};

export default FilePreview;



const FontIcon = ({ name }) => {
  const suffix = name ? name.split('.').pop().toLowerCase() : '';

  let char = '';
  let bg = 'bg-gray-500';

  switch (suffix) {
    case 'html':
      char = 'H';
      bg = 'bg-red-500';
      break;
    case 'txt':
      char = 'Txt';
      bg = 'bg-gray-300';
      break;
    case 'md':
      char = 'M';
      break;
    case 'doc':
    case 'docx':
      char = 'W';
      bg = 'bg-blue-500';
      break;
    case 'xls':
    case 'xlsx':
      char = 'X';
      bg = 'bg-green-500';
      break;
    case 'ppt':
    case 'pptx':
      char = 'ppt';
      bg = 'bg-orange-500';
      break;
    case 'pdf':
      char = 'P';
      bg = 'bg-red-500';
      break;
    case 'jpg':
    case 'jpeg':
    case 'png':
    case 'gif':
      char = 'I';
      bg = 'bg-purple-500';
      break;
    // 可以继续添加其他文件类型...
  }

  return (
    <div className={`size-full flex items-center justify-center font-bold 
      ${bg} text-white`}>
      {char}
    </div>
  );
};