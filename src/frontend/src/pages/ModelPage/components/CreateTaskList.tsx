import { HelpCircle, Loader2 } from "lucide-react";
import { useContext, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Badge } from "../../../components/ui/badge";
import { Button } from "../../../components/ui/button";
import { Checkbox } from "../../../components/ui/checkbox";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "../../../components/ui/tooltip";
import { PopUpContext } from "../../../contexts/popUpContext";
import { getFileUrlApi, getPresetFileApi, uploadTaskFileApi } from "../../../controllers/API/finetune";
import { downloadFile, downloadJson } from "../../../util/utils";
import { checkSassUrl } from "../../ChatAppPage/components/FileView";
import UploadModal from "./UploadModal";
import sampleData from "./sampleData";

export default function CreateTaskList({ onChange }) {
    const { t } = useTranslation()

    const { openPopUp, closePopUp } = useContext(PopUpContext);
    // 预设集
    const { prsetList, handleChangePrsetList } = usePresetList(onChange)
    const [downloadMap, setDownloadMap] = useState({}) // 下载loading
    // 个人数据集
    const { userList, setUserList, handleChangeUserList, handleUploadUserList } = useUserList(onChange);

    const [isCustom, setIsCustom] = useState(false)

    const handleDownloadFile = async (data) => {
        const res = await getFileUrlApi(data.dataSource)
        setDownloadMap(map => ({ ...map, [data.id]: true }))
        await downloadFile(checkSassUrl(res.url), data.name)
        setDownloadMap(map => ({ ...map, [data.id]: false }))
    }

    return <div>
        <div className="flex justify-between">
            <div>
                <Button size="sm" className="rounded-full h-7" onClick={() => openPopUp(<UploadModal
                    fileName="files"
                    accept={['json']}
                    onClose={closePopUp}
                    onUpload={uploadTaskFileApi}
                    onSubmit={(res) => handleUploadUserList(res, closePopUp)}
                />)}>{t('finetune.uploadDataset')}</Button>
                <Button variant="link" onClick={() => downloadJson(sampleData)}>{t('finetune.downloadSampleFile')}</Button>
            </div>
            <div className="flex gap-2 items-center">
                <Checkbox checked={isCustom} onCheckedChange={(val: boolean) => setIsCustom(val)} />
                <Label>{t('finetune.customSampleSize')}</Label>
                <TooltipProvider>
                    <Tooltip>
                        <TooltipTrigger><HelpCircle size={18} /></TooltipTrigger>
                        <TooltipContent>
                            <p>{t('finetune.customSampleSizeTooltip1')}</p>
                            <p>{t('finetune.customSampleSizeTooltip2')}</p>
                            <p>{t('finetune.customSampleSizeTooltip3')}</p>
                        </TooltipContent>
                    </Tooltip>
                </TooltipProvider>
            </div>
        </div>
        <div className="border rounded-md p-4 overflow-y-auto max-h-[400px] mt-4 shadow-md bg-gray-100 dark:bg-gray-800">
            <p className="text-sm text-muted-foreground mt-4">{t('finetune.presetDatasets')}</p>
            {
                prsetList.length ? prsetList.map((data, i) =>
                    <div key={data.id} className="flex gap-4 items-center mt-2 h-8 hover:bg-gray-200 dark:hover:bg-gray-600">
                        <Checkbox
                            checked={data.checked}
                            onCheckedChange={(val: boolean) => handleChangePrsetList(data.id, 'checked', val)} />
                        <span className="text-sm">{data.name}</span>
                        <div className="flex ml-auto gap-4">
                            <Button size="sm" variant="outline"
                                disabled={downloadMap[data.id]}
                                onClick={() => handleDownloadFile(data)}
                                className="rounded-full h-6 px-4 ml-auto">
                                {downloadMap[data.id] && <Loader2 className="animate-spin mr-2" size={14} />}
                                {t('finetune.download')}</Button>
                            {isCustom ?
                                <Input
                                    placeholder={t('finetune.sampleSize')}
                                    type="number"
                                    value={data.sampleSize}
                                    onChange={(e) => handleChangePrsetList(data.id, 'sampleSize', e.target.value)}
                                    className="bg-[#fff] rounded-full w-28 h-6"
                                ></Input> :
                                <Badge variant="outline" className="text-sm">{t('finetune.sampleSize')}:{data.sampleSize}</Badge>}
                        </div>
                    </div>)
                    : <div className=" text-gray-400 text-sm mt-4 indent-2">{t('finetune.noData')}</div>
            }
            <p className="text-sm text-muted-foreground mt-4">{t('finetune.userDatasets')}</p>
            {
                userList.length ? userList.map(data =>
                    <div className="flex gap-4 items-center mt-2 h-8 hover:bg-gray-200">
                        <Checkbox
                            checked={data.checked}
                            onCheckedChange={(val: boolean) => handleChangeUserList(data.id, 'checked', val)} />
                        <span className="text-sm">{data.name}</span>
                        <div className="flex ml-auto gap-4">
                            <Button
                                size="sm"
                                variant="destructive"
                                className="rounded-full h-6 px-4"
                                onClick={() => {
                                    setUserList((prev) => {
                                        const newData = prev.filter(el => el.id !== data.id)
                                        onChange('train_data', newData)
                                        return newData
                                    })
                                }}
                            >{t('delete')}</Button>
                            {isCustom ?
                                <Input
                                    placeholder={t('finetune.sampleSizePlaceholder')}
                                    type="number"
                                    value={data.sampleSize}
                                    onChange={(e) => handleChangeUserList(data.id, 'sampleSize', e.target.value)}
                                    className="bg-[#fff] rounded-full w-28 h-6"
                                ></Input> :
                                <Badge variant="outline" className="text-sm">{t('finetune.sampleSize')}:{data.sampleSize}</Badge>}
                        </div>
                    </div>)
                    : <div className=" text-gray-400 text-sm mt-4 indent-2">{t('finetune.noData')}</div>
            }
        </div>
    </div>
};


// 预设集
export function usePresetList(onChange) {
    const [prsetList, setPrsetList] = useState([]);

    useEffect(() => {
        getPresetFileApi().then(setPrsetList);
    }, []);

    const handleChangePrsetList = (id, key, val) => {
        setPrsetList((prevState) => {
            const newState = prevState.map(item =>
                item.id === id ? { ...item, [key]: val } : item);

            onChange('preset_data', newState);
            return newState;
        });
    };

    return { prsetList, handleChangePrsetList };
}

// 个人数据集
export function useUserList(onChange) {
    const [userList, setUserList] = useState([]);

    const handleUploadUserList = (res, closePopUp) => {
        setUserList(state => {
            const newState = [...res[0], ...state];
            onChange('train_data', newState);
            return newState;
        });
        closePopUp();
    };

    const handleChangeUserList = (id, key, val) => {
        setUserList((prevState) => {
            const newState = prevState.map(item =>
                item.id === id ? { ...item, [key]: val } : item);

            onChange('train_data', newState);
            return newState;
        });
    };

    return { userList, setUserList, handleChangeUserList, handleUploadUserList };
}