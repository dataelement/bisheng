import { uploadLibFile } from "../../controllers/API";

// Function to upload the file with progress tracking
export const uploadFileWithProgress = async (file, callback, type: 'knowledge' | 'icon' = 'knowledge', url): Promise<any> => {
  try {
    const formData = new FormData();
    formData.append('file', file);

    const config = {
      headers: { 'Content-Type': 'multipart/form-data;charset=utf-8' },
      onUploadProgress: (progressEvent) => {
        const { loaded, total } = progressEvent;
        const progress = Math.round((loaded * 100) / total);
        console.log(`Upload progress: ${file.name} ${progress}%`);
        callback(progress)
        // You can update your UI with the progress information here
      },
    };

    // Convert the FormData to binary using the FileReader API
    const data = await uploadLibFile(formData, config, type, url);

    data && callback(100);

    console.log('Upload complete:', data);
    return data
    // Handle the response data as needed
  } catch (error) {
    console.error('Error uploading file:', error);
    return ''
    // Handle errors
  }
};
