// @ts-strict-ignore
import { locationContext } from "@/contexts/locationContext";
import { MAX_MEDIA_FILES, isMediaFileName } from "@/util/fileAcceptUtils";
import { FileSearch2 } from "lucide-react";
import { useContext, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { alertContext } from "../../contexts/alertContext";
import { TabsContext } from "../../contexts/tabsContext";
import { uploadFile } from "../../controllers/API";
import { uploadFileWithProgress } from "../../modals/UploadModal/upload";
import { FileComponentType } from "../../types/components";
import { LoadIcon } from "../bs-icons/loading";
import { Button } from "../bs-ui/button";
import { useToast } from "../bs-ui/toast/use-toast";

export default function InputFileComponent({
  value,
  onChange,
  disabled,
  suffixes = [],
  fileTypes,
  placeholder = 'The current file is empty',
  onFileChange,
  editNode = false,
  isSSO = false,
  multiple = false
}: FileComponentType) {
  const { t } = useTranslation();
  const [myValue, setMyValue] = useState(value);
  const [loading, setLoading] = useState(false);
  // Callers pass either a suffix array (node params) or an `.a,.b` accept string (form input).
  const suffixList = Array.isArray(suffixes)
    ? suffixes
    : String(suffixes || "").split(",").filter(Boolean);
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
    for (let index = 0; index < suffixList.length; index++) {
      if (fileName.endsWith(suffixList[index])) {
        return true;
      }
    }
    return false;
  }

  useEffect(() => {
    setMyValue(value);
  }, [value]);

  const { appConfig } = useContext(locationContext)
  const { toast } = useToast()
  const checkFileSize = (file) => {
    const maxSize = (appConfig.uploadFileMaxSize || 50) * 1024 * 1024;
    if (file.size > maxSize) {
      return t('chat.fileExceedRemoved', { name: file.name, size: appConfig.uploadFileMaxSize })
    }
    return ''
  }

  const handleButtonClick = () => {
    if (multiple) return batchUpload()
    // Create a file input element
    const input = document.createElement("input");
    input.type = "file";
    input.accept = suffixList.join(",");
    input.style.display = "none"; // Hidden from view
    input.multiple = false; // Allow only one file selection

    input.onchange = (e: Event) => {
      setLoading(true);

      // Get the selected file
      const file = (e.target as HTMLInputElement).files?.[0];

      const errorMsg = checkFileSize(file)
      if (errorMsg) {
        toast({
          variant: 'error',
          description: errorMsg
        })
        return setLoading(false);
      }
      // Check if the file type is correct
      // if (file && checkFileType(file.name)) {
      // Upload the file
      isSSO ? uploadFileWithProgress(file, (progress) => { }).then(res => {
        setLoading(false);
        if (typeof res === 'string') return toast({
          variant: 'error',
          description: res
        })
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
    input.accept = suffixList.join(",");
    input.style.display = "none"; // Hidden from view
    input.multiple = true; // Allow multiple file selection

    input.onchange = (e: Event) => {
      setLoading(true);

      // Get the selected files
      const _files = (e.target as HTMLInputElement).files;

      if (_files && _files.length > 0) {
        const filePaths = []; // This will hold the file paths after successful upload

        const errorMsgs = []
        const files = []
        for (let i = 0; i < _files.length; i++) {
          const errorMsg = checkFileSize(_files[i])
          errorMsg ? errorMsgs.push(errorMsg) : files.push(_files[i])
        }

        if (errorMsgs.length) {
          toast({
            variant: 'error',
            description: errorMsgs
          })
          // 文件都不符合要求 结束上传
          if (errorMsgs.length === _files.length) {
            return setLoading(false);
          }
        }

        // Audio/video is transcribed, not text-extracted: every clip holds an ASR
        // slot for the whole run. Same cap the end-user chat enforces, applied to
        // the picked batch — a form field replaces its value rather than appending.
        if (files.filter((file) => isMediaFileName(file.name)).length > MAX_MEDIA_FILES) {
          toast({
            variant: 'error',
            description: t('chat.mediaFileTooMany')
          })
          return setLoading(false);
        }

        const fileNames = Array.from(files).map(file => file.name); // Extract file names

        // Perform the upload for each file
        const uploadPromises = Array.from(files).map(file => {
          return isSSO
            ? uploadFileWithProgress(file, (progress) => { }) // Adjust upload method if needed
              .then(res => {
                if (typeof res === 'string') {
                  setErrorData({ title: "Error", list: [res] });
                  toast({
                    variant: 'error',
                    description: res
                  })
                  setLoading(false);
                  throw new Error(res); // Exit the upload if error occurs
                }
                return res.file_path
              })
            : uploadFile(file, flow.id).then((data) => {
              console.log("File uploaded successfully");
              return data.file_path
            });
        });

        // Wait for all file uploads to finish
        Promise.all(uploadPromises)
          .then((filePaths) => {
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
        toast({
          variant: 'error',
          description: t('chat.noFileSelected')
        })
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
