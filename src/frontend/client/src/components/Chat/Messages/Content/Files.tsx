import { useMemo, memo } from 'react';
import type { TFile, TMessage } from '~/data-provider/data-provider/src';
import FileContainer from '~/components/Chat/Input/Files/FileContainer';
import Image from './Image';

const Files = ({ message }: { message?: TMessage }) => {
  const imageFiles = useMemo(() => {
    const images = message?.files?.filter((file) => file.type?.startsWith('image/')) || [];
    return images.map(file => ({ ...file, filepath: file.filepath?.replace(/^https?:\/\/[^\/]+/, __APP_ENV__.BASE_URL) }))
  }, [message?.files]);

  const otherFiles = useMemo(() => {
    return message?.files?.filter((file) => !(file.type?.startsWith('image/') === true)) || [];
  }, [message?.files]);

  return (
    <>
      {otherFiles.length > 0 &&
        otherFiles.map((file) => <FileContainer key={file.file_id} file={file as TFile} />)}
      {imageFiles.length > 0 &&
        imageFiles.map((file) => (
          <Image
            key={file.file_id}
            imagePath={file.preview ?? file.filepath ?? ''}
            height={file.height ?? 1920}
            width={file.width ?? 1080}
            altText={file.filename ?? 'Uploaded Image'}
            placeholderDimensions={{
              height: `${file.height ?? 1920}px`,
              width: `${file.height ?? 1080}px`,
            }}
          // n={imageFiles.length}
          // i={i}
          />
        ))}
    </>
  );
};

export default memo(Files);
