import { useEffect, useState } from "react";
import { DragDropContext, Draggable, Droppable } from 'react-beautiful-dnd';
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

export default function Templates({ onBack }) {

    const [temps, setTemps] = useState([])
    useEffect(() => {
        readTempsDatabase().then(res => {
            setTemps(res)
        })
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
        updateTempApi(currentItem.id, { name, description, order_num })
        console.log('sort :>> ', sort);
    }

    const handleDelTemp = (index: number, id: number) => {
        deleteTempApi(id)
        setTemps(temps.filter((temp, i) => index !== i));
    }

    return <div className="p-6">
        <div className="flex justify-end">
            <Button className="h-8 rounded-full" onClick={onBack}>返回技能列表</Button>
        </div>
        <p className="text-gray-500">技能模板管理，模板对所有用户可见，支持拖拽排序、删除操作</p>

        <Table className="mt-10">
            <TableHeader>
                <TableRow>
                    <TableHead className="w-[400px]">模板名称</TableHead>
                    <TableHead>模板描述</TableHead>
                    <TableHead>操作</TableHead>
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
                                                <a href="javascript:;" onClick={() => handleDelTemp(index, temp.id)} className="underline">删除</a>
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

        {/* // <div className="w-full flex flex-wrap mt-6"
                    //     {...provided.droppableProps}
                    //     ref={provided.innerRef}
                    // >
                    //     {temps.map((temp: any, index: number) => (
                    //         <Draggable key={'drag' + temp.flow_id} draggableId={'drag' + temp.flow_id} index={index}>
                    //             {(provided) => (
                    //                 <div
                    //                     className='drag-li'
                    //                     ref={provided.innerRef}
                    //                     {...provided.draggableProps}
                    //                     {...provided.dragHandleProps}
                    //                 >
                    //                     <TempItem data={temp} onDelete={() => { }}></TempItem>
                    //                 </div>
                    //             )}
                    //         </Draggable>
                    //     ))}
                    //     {provided.placeholder}
                    // </div> */}
    </div >
};
