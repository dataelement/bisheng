import { useEffect,useRef,useState } from "react";
export const useFileLoading = (locked: boolean) => {
    const [loading, setLoading] = useState(false);
    const filesRef = useRef<string[]>([])
    useEffect(() => {
        if (locked) filesRef.current = []
    }, [locked])
    return {
        fileUploading: loading,
        getFileIds: () => filesRef.current,
        loadingChange(files: string[] | null) {
            if (files) {
                setLoading(false)
                filesRef.current = files
            } else {
                setLoading(true)
                filesRef.current = []
            }
        },
        clear() {
            setLoading(false)
            filesRef.current = []
        }
    }
}
