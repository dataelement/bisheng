import { FileSearch2 } from "lucide-react";
import { useContext, useEffect, useState } from "react";
import { alertContext } from "../../contexts/alertContext";
import { TabsContext } from "../../contexts/tabsContext";
import { uploadFile } from "../../controllers/API";
import { FileComponentType } from "../../types/components";
import { uploadFileWithProgress } from "../../modals/UploadModal/upload";

export default function InputFileComponent({
  value,
  onChange,
  disabled,
  suffixes,
  fileTypes,
  placeholder = 'The current file is empty',
  onFileChange,
  editNode = false,
  isSSO = false
}: FileComponentType) {
  const [myValue, setMyValue] = useState(value);
  const [loading, setLoading] = useState(false);
  const { setErrorData } = useContext(alertContext);
  const { tabId } = useContext(TabsContext);
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
        if (typeof res === 'string') return setErrorData({title: "Error", list: [res]})
        const { file_path } = res;
        setMyValue(file.name);
        onChange(file.name);
        // sets the value that goes to the backend
        onFileChange(file_path);
      }) : uploadFile(file, tabId)
        .then((res) => res.data)
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
        <button onClick={handleButtonClick}>
          {!editNode && !loading && (
            <FileSearch2
              strokeWidth={1.5}
              className={
                "icons-parameters-comp" +
                (disabled ? " text-ring " : " hover:text-accent-foreground")
              }
            />
          )}
          {!editNode && loading && (
            <span className="loading loading-spinner loading-sm pointer-events-none h-8 pl-3"></span>
          )}
        </button>
      </div>
    </div>
  );
}
