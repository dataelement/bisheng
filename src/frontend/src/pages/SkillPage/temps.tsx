import { useEffect, useState } from "react";
import { DragDropContext, Draggable, Droppable } from 'react-beautiful-dnd';
import { useTranslation } from "react-i18next";
import { bsconfirm } from "../../alerts/confirm";
import { Button } from "../../components/ui/button";
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow
} from "../../components/ui/table";
import { deleteTempApi, readTempsDatabase, updateTempApi } from "../../controllers/API";
import { captureAndAlertRequestErrorHoc } from "../../controllers/request";

export default function Templates({ onBack, onChange }) {
    const { t } = useTranslation()

    const [temps, setTemps] = useState([])
    useEffect(() => {
        readTempsDatabase().then(setTemps)
    }, [])

    const handleDragEnd = ({ source, destination }: any) => {
        if (!destination || source.index === destination.index) {
            return;
        }
        const updatedList = [...temps];
        const [removed] = updatedList.splice(source.index, 1);
        updatedList.splice(destination.index, 0, removed);
        setTemps(updatedList);
        // 65535 sort
        let sort = 0
        if (destination.index === 0) {
            sort = updatedList[1].order_num + 65535
        } else if (destination.index === updatedList.length - 1) {
            sort = updatedList.at(-2).order_num - 65535
        } else {
            const startSort = updatedList[destination.index - 1].order_num
            const endSort = updatedList[destination.index + 1].order_num
            sort = startSort + (endSort - startSort) / 2
        }

        const currentItem = updatedList[destination.index]
        currentItem.order_num = sort
        const { name, description, order_num } = currentItem
        captureAndAlertRequestErrorHoc(updateTempApi(currentItem.id, { name, description, order_num }).then(onChange))
    }

    const handleDelTemp = (index: number, id: number) => {
        bsconfirm({
            desc: t('skills.confirmText'),
            okTxt: t('delete'),
            onOk(next) {
                captureAndAlertRequestErrorHoc(deleteTempApi(id).then((res) => {
                    onChange(res)
                    setTemps(temps.filter((temp, i) => index !== i));
                    next()
                }))
            }
        })
    }

    return <div className="p-6 h-screen overflow-y-auto">
        <div className="flex justify-end">
            <Button className="h-8 rounded-full" onClick={onBack}>{t('skills.backToSkillList')}</Button>
        </div>
        <p className="text-gray-500">{t('skills.skillTemplateManagement')}</p>

        <Table className="mt-10">
            <TableHeader>
                <TableRow>
                    <TableHead className="w-[400px]">{t('skills.templateName')}</TableHead>
                    <TableHead>{t('skills.templateDescription')}</TableHead>
                    <TableHead>{t('operations')}</TableHead>
                </TableRow>
            </TableHeader>
            <DragDropContext onDragEnd={handleDragEnd}>
                <Droppable droppableId={'list'}>
                    {(provided) => (
                        <TableBody  {...provided.droppableProps} ref={provided.innerRef}>
                            {temps.map((temp, index) =>
                                <Draggable key={'drag' + temp.id} draggableId={'drag' + temp.id} index={index}>
                                    {(provided) => (
                                        <tr
                                            className='drag-li border-b'
                                            ref={provided.innerRef}
                                            {...provided.draggableProps}
                                            {...provided.dragHandleProps}
                                        >
                                            <TableCell className="font-medium min-w-[400px]">{temp.name}</TableCell>
                                            <TableCell>{temp.description}</TableCell>
                                            <TableCell className="">
                                                <a href="javascript:;" onClick={() => handleDelTemp(index, temp.id)} className="underline">{t('delete')}</a>
                                            </TableCell>
                                        </tr>
                                    )}
                                </Draggable>
                            )}
                        </TableBody>
                    )}
                </Droppable>
            </DragDropContext>
        </Table>
    </div>
};
