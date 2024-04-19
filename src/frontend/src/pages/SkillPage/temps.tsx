import { useEffect, useState } from "react";
import { DragDropContext, Draggable, Droppable } from 'react-beautiful-dnd';
import { useTranslation } from "react-i18next";
import { Button } from "../../components/bs-ui/button";
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow
} from "../../components/bs-ui/table";
import { deleteTempApi, readTempsDatabase, updateTempApi } from "../../controllers/API";
import { captureAndAlertRequestErrorHoc } from "../../controllers/request";
import { useNavigate } from "react-router-dom";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";

export default function Templates() {
    const navigate = useNavigate()

    const onChange = () => { }
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
        bsConfirm({
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

    return <div className="px-2 py-4 h-full relative">
        <div className="h-full w-full overflow-y-auto overflow-x-hidden scrollbar-hide">
            <div className="flex justify-end">
                <Button className="h-10 px-8" size="sm" onClick={() => navigate('/build/skills')}>{t('skills.backToSkillList')}</Button>
            </div>
            <Table className="mb-[50px]">
                <TableHeader>
                    <TableRow>
                        <TableHead className="w-[400px]">{t('skills.templateName')}</TableHead>
                        <TableHead>{t('skills.templateDescription')}</TableHead>
                        <TableHead className="text-right pr-10">{t('operations')}</TableHead>
                    </TableRow>
                </TableHeader>
                <DragDropContext onDragEnd={handleDragEnd}>
                    <Droppable droppableId={'list'}>
                        {(provided) => (
                            <TableBody  {...provided.droppableProps} ref={provided.innerRef}>
                                {temps.map((temp, index) =>
                                    <Draggable key={'drag' + temp.id} draggableId={'drag' + temp.id} index={index}>
                                        {(provided, snapshot) => (
                                            <tr
                                                className='group drag-li hover:bg-muted/50 data-[state=selected]:bg-muted'
                                                ref={provided.innerRef}
                                                {...provided.draggableProps}
                                                {...provided.dragHandleProps}
                                                style={{ ...provided.draggableProps.style }}
                                            >
                                                <TableCell className="font-medium min-w-[400px]">{temp.name}</TableCell>
                                                <TableCell className={snapshot.isDragging ? 'break-words' : `max-w-0 break-words`}>{temp.description}</TableCell>
                                                <TableCell className="text-right pr-5">
                                                    <Button variant="link" onClick={() => handleDelTemp(index, temp.id)}>{t('delete')}</Button>
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
        {/* footer */}
        <div className="flex justify-between items-center absolute bottom-0 right-0 w-full py-4 bg-[white] pl-[16px] h-[60px]">
            <p className="text-gray-500 text-sm">{t('skills.skillTemplateManagement')}</p>
            <span></span>
        </div>
    </div>
};
