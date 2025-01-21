import { FileSearch2 } from "lucide-react";
import { useContext, useEffect, useState } from "react";
import { alertContext } from "../../contexts/alertContext";
import { TabsContext } from "../../contexts/tabsContext";
import { uploadFile } from "../../controllers/API";
import { uploadFileWithProgress } from "../../modals/UploadModal/upload";
import { FileComponentType } from "../../types/components";
import { LoadIcon } from "../bs-icons/loading";
import { Button } from "../bs-ui/button";

export default function InputFileComponent({
  value,
  onChange,
  disabled,
  suffixes,
  fileTypes,
  placeholder = 'The current file is empty',
  onFileChange,
  editNode = false,
  isSSO = false,
  multiple = false
}: FileComponentType) {
  const [myValue, setMyValue] = useState(value);
  const [loading, setLoading] = useState(false);
  const { setErrorData } = useContext(alertContext);
  const { flow } = useContext(TabsContext);
  useEffect(() => {
    if (disabled) {
      setMyValue("");
      onChange("");
      onFileChange("");
    }
  }, [disabled, onChange]);

  function checkFileType(fileName: string): boolean {
    for (let index = 0; index < suffixes.length; index++) {
      if (fileName.endsWith(suffixes[index])) {
        return true;
      }
    }
    return false;
  }

  useEffect(() => {
    setMyValue(value);
  }, [value]);

  const handleButtonClick = () => {
    if (multiple) return batchUpload()
    // Create a file input element
    const input = document.createElement("input");
    input.type = "file";
    input.accept = suffixes.join(",");
    input.style.display = "none"; // Hidden from view
    input.multiple = false; // Allow only one file selection

    input.onchange = (e: Event) => {
      setLoading(true);

      // Get the selected file
      const file = (e.target as HTMLInputElement).files?.[0];

      // Check if the file type is correct
      // if (file && checkFileType(file.name)) {
      // Upload the file
      isSSO ? uploadFileWithProgress(file, (progress) => { }).then(res => {
        setLoading(false);
        if (typeof res === 'string') return setErrorData({ title: "Error", list: [res] })
        const { file_path } = res;
        setMyValue(file.name);
        onChange(file.name);
        // sets the value that goes to the backend
        onFileChange(file_path);
      }) : uploadFile(file, flow.id)
        .then((data) => {
          console.log("File uploaded successfully");
          // Get the file name from the response
          const { file_path } = data;

          // Update the state and callback with the name of the file
          // sets the value to the user
          setMyValue(file.name);
          onChange(file.name);
          // sets the value that goes to the backend
          onFileChange(file_path);
          setLoading(false);
        })
        .catch(() => {
          console.error("Error occurred while uploading file");
          setLoading(false);
        });
      // } else {
      //   // Show an error if the file type is not allowed
      //   setErrorData({
      //     title:
      //       "请选择有效文件。只允许使用这些文件类型：",
      //     list: fileTypes,
      //   });
      //   setLoading(false);
      // }
    };

    // Trigger the file selection dialog
    input.click();
  };

  const batchUpload = () => {
    // Create a file input element
    const input = document.createElement("input");
    input.type = "file";
    input.accept = suffixes.join(",");
    input.style.display = "none"; // Hidden from view
    input.multiple = true; // Allow multiple file selection

    input.onchange = (e: Event) => {
      setLoading(true);

      // Get the selected files
      const files = (e.target as HTMLInputElement).files;

      if (files && files.length > 0) {
        const fileNames = Array.from(files).map(file => file.name); // Extract file names
        const filePaths = []; // This will hold the file paths after successful upload

        // Perform the upload for each file
        const uploadPromises = Array.from(files).map(file => {
          return isSSO
            ? uploadFileWithProgress(file, (progress) => { }) // Adjust upload method if needed
              .then(res => {
                if (typeof res === 'string') {
                  setErrorData({ title: "Error", list: [res] });
                  setLoading(false);
                  throw new Error(res); // Exit the upload if error occurs
                }
                const { file_path } = res;
                filePaths.push(file_path); // Store file paths
              })
            : uploadFile(file, flow.id).then((data) => {
              console.log("File uploaded successfully");
              const { file_path } = data;
              filePaths.push(file_path); // Store file paths
            });
        });

        // Wait for all file uploads to finish
        Promise.all(uploadPromises)
          .then(() => {
            // After all files are uploaded successfully, update the state
            setMyValue(fileNames.join(",")); // Join file names with commas
            onChange(fileNames); // Pass an array of file names
            onFileChange(filePaths); // Pass an array of file paths

            setLoading(false); // Hide loading state
          })
          .catch((error) => {
            console.error("Error occurred while uploading files", error);
            setLoading(false); // Hide loading state if an error occurs
          });
      } else {
        setErrorData({
          title: "请选择文件",
          list: ["没有选择文件"],
        });
        setLoading(false); // Hide loading state if no files were selected
      }
    };

    // Trigger the file selection dialog
    input.click();
  };



  return (
    <div className={disabled ? "input-component-div" : "w-full"}>
      <div className="input-file-component">
        <span
          onClick={handleButtonClick}
          className={
            editNode
              ? "input-edit-node input-dialog text-muted-foreground"
              : disabled
                ? "input-disable input-dialog input-primary"
                : "input-dialog input-primary text-muted-foreground"
          }
        >
          {myValue !== "" ? myValue : placeholder}
        </span>
        <Button size="icon" variant="ghost" onClick={handleButtonClick}>
          {!editNode && !loading && (
            <FileSearch2
              strokeWidth={1.5}
              className={
                (disabled ? " text-ring " : " hover:text-accent-foreground")
              }
            />
          )}
          {!editNode && loading && (<LoadIcon className="text-primary duration-300 pointer-events-none" />)}
        </Button>
      </div>
    </div>
  );
}
