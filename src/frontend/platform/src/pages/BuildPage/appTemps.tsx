// @ts-strict-ignore
import { Button } from '@bisheng/ui';
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { AppType } from "@/types/app";
import { useContext, useEffect, useRef, useState } from "react";
import { DragDropContext, Draggable, Droppable } from '@hello-pangea/dnd';
import { useTranslation } from "react-i18next";
import { Navigate, useNavigate, useParams } from "react-router-dom";
import { userContext } from '@/contexts/userContext';
import { canManageAppTemplates } from './templatePermissions';

import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow
} from "../../components/bs-ui/table";
import { deleteTempApi, readTempsDatabase, updateTempApi } from "../../controllers/API";
import { showApiError } from "../../controllers/request";
import { SelectType } from "./apps";

export default function Templates() {
    const navigate = useNavigate()
    const { user } = useContext(userContext);
    const canManageTemplates = canManageAppTemplates(user);
    const generation = useRef(0);

    const onChange = () => { }
    const { t } = useTranslation('flow')

    const { type } = useParams()
    const [temps, setTemps] = useState([])
    useEffect(() => {
        let active = true;
        const load = () => {
            const request = ++generation.current;
            setTemps([]);
            if (!canManageTemplates) return;
            readTempsDatabase(type).then(rows => {
                if (active && request === generation.current) setTemps(rows);
            }).catch(error => {
                if (active && request === generation.current) showApiError(error);
            });
        };
        load();
        window.addEventListener('bisheng:management-scope-changed', load);
        const invalidate = () => { active = false; ++generation.current; };
        return () => {
            invalidate();
            window.removeEventListener('bisheng:management-scope-changed', load);
        };
    }, [type, canManageTemplates, user?.tenant_id])

    const handleDragEnd = ({ source, destination }: any) => {
        if (!destination || source.index === destination.index) {
            return;
        }
        const previousList = temps;
        const request = generation.current;
        const updatedList = temps.map(temp => ({ ...temp }));
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
        const { order_num } = currentItem

        updateTempApi(currentItem.id, { order_num }).then(onChange).catch(error => {
            if (request === generation.current) setTemps(previousList)
            showApiError(error)
        })
    }

    const handleDelTemp = (index: number, id: number) => {
        const request = generation.current;
        const nameMap = {
            [AppType.FLOW]: t('workflow'),
            [AppType.ASSISTANT]: t('assistant')
        };
        const labelName = nameMap[type]
        bsConfirm({
            desc: t('confirmDeleteTemplate', { type: labelName }),
            okTxt: t('delete'),
            onOk(next) {
                if (request !== generation.current) { next(); return; }
                return deleteTempApi(id).then((res) => {
                    onChange(res)
                    if (request === generation.current) setTemps(rows => rows.filter(temp => temp.id !== id));
                    next()
                })
            }
        })
    }

    if (!canManageTemplates) return <Navigate to="/403" replace />;

    return <div className="px-2 py-4 h-full relative">
        <div className="h-full w-full overflow-y-auto overflow-x-hidden scrollbar-hide">
            <div className="flex justify-between">
                <SelectType defaultValue={type} onChange={(v) => navigate(`/build/temps/${v}`)} />
                <Button size="small" onClick={() => navigate('/build/apps')}>{t('returnToAppList')}</Button>
            </div>
            <Table className="mb-[50px]">
                <TableHeader>
                    <TableRow>
                        <TableHead className="w-[400px]">{t('templateName')}</TableHead>
                        <TableHead>{t('templateDescription')}</TableHead>
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
                                                style={{
                                                    ...provided.draggableProps.style,
                                                    display: snapshot.isDragging ? 'table' : ''
                                                }}
                                            >
                                                <TableCell className="font-medium min-w-[400px]">{temp.name}</TableCell>
                                                <TableCell className={snapshot.isDragging ? 'break-words' : `max-w-0 break-words`}>{temp.description}</TableCell>
                                                <TableCell className="text-right pr-5">
                                                    <Button size="small" variant="link" color="danger" onClick={() => handleDelTemp(index, temp.id)}>{t('delete')}</Button>
                                                </TableCell>
                                            </tr>
                                        )}
                                    </Draggable>
                                )}
                                {provided.placeholder}
                            </TableBody>
                        )}
                    </Droppable>
                </DragDropContext>
            </Table>
        </div>
        {/* footer */}
        <div className="flex justify-between items-center absolute bottom-0 right-0 w-full py-4 pl-[16px] h-[60px] bg-background-login">
            <p className="text-gray-500 text-sm">{t('templateManagementDescription')}</p>
            <span></span>
        </div>
    </div>
};
