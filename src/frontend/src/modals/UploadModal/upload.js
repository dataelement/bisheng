import { uploadLibFile } from "../../controllers/API";

// Function to upload the file with progress tracking
export const uploadFileWithProgress = async (file, callback) => {
  try {
    const formData = new FormData();
    formData.append('file', file);

    const config = {
      headers: {'Content-Type': 'multipart/form-data;charset=utf-8'},
      onUploadProgress: (progressEvent) => {
        const { loaded, total } = progressEvent;
        const progress = Math.round((loaded * 100) / total);
        console.log(`Upload progress: ${file.name} ${progress}%`);
        callback(progress)
        // You can update your UI with the progress information here
      },
    };

    // Convert the FormData to binary using the FileReader API
    const response = await uploadLibFile(formData, config);

    console.log('Upload complete:', response.data);
    return response.data
    // Handle the response data as needed
  } catch (error) {
    console.error('Error uploading file:', error);
    return error.response.statusText || 'Upload error'
    // Handle errors
  }
};
