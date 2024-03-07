import { useContext, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "../../../components/ui/button";
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow
} from "../../../components/ui/table";
import { userContext } from "../../../contexts/userContext";
import { disableUserApi, getUsersApi } from "../../../controllers/API/user";
import UserRoleModal from "./UserRoleModal";
import { captureAndAlertRequestErrorHoc } from "../../../controllers/request";
import { useTable } from "../../../util/hook";
import { Input } from "../../../components/ui/input";
import PaginationComponent from "../../../components/PaginationComponent";
import { Search } from "lucide-react";

export default function Users(params) {
    const { user } = useContext(userContext);
    const { t } = useTranslation()

    const { page, pageSize, data: users, total, loading, setPage, search, reload } = useTable((param) =>
        getUsersApi(param.keyword, param.page, param.pageSize)
    )

    // 禁用
    const { delShow, idRef, close, delConfim } = useDelete()
    const handleDelete = () => {
        captureAndAlertRequestErrorHoc(disableUserApi(idRef.current.user_id, 1).then(res => {
            reload()
            close()
        }))
    }
    const handleEnableUser = (user) => {
        captureAndAlertRequestErrorHoc(disableUserApi(user.user_id, 0).then(res => {
            reload()
            close()
        }))
    }

    // 编辑
    const [roleOpenId, setRoleOpenId] = useState(null)
    const handleRoleChange = () => {
        setRoleOpenId(null)
        reload()
    }

    return <>
        <div className="flex justify-end">
            <div className="w-[180px] relative">
                <Input placeholder={t('system.username')} onChange={(e) => search(e.target.value)}></Input>
                <Search className="absolute right-4 top-2 text-gray-300 pointer-events-none"></Search>
            </div>
        </div>
        <Table>
            {/* <TableCaption>用户列表.</TableCaption> */}
            <TableHeader>
                <TableRow>
                    <TableHead className="w-[200px]">{t('system.username')}</TableHead>
                    <TableHead>{t('createTime')}</TableHead>
                    <TableHead className="text-right">{t('operations')}</TableHead>
                </TableRow>
            </TableHeader>
            <TableBody>
                {users.map((el) => (
                    <TableRow key={el.id}>
                        <TableCell className="font-medium max-w-md truncate">{el.user_name}</TableCell>
                        {/* <TableCell>{el.role}</TableCell> */}
                        <TableCell>{el.update_time.replace('T', ' ')}</TableCell>
                        <TableCell className="text-right">
                            {user.user_id === el.user_id ? <a href="javascript:;" className=" ml-4 text-gray-400">{t('edit')}</a> :
                                <a href="javascript:;" onClick={() => setRoleOpenId(el.user_id)} className="underline ml-4">{t('edit')}</a>}
                            {
                                el.delete === 1 ? <a href="javascript:;" onClick={() => handleEnableUser(el)} className="underline ml-4">{t('enable')}</a> :
                                    user.user_id === el.user_id ? <a href="javascript:;" className=" ml-4 text-gray-400">{t('disable')}</a> :
                                        <a href="javascript:;" onClick={() => delConfim(el)} className="underline ml-4 text-red-500">{t('disable')}</a>
                            }
                        </TableCell>
                    </TableRow>
                ))}
            </TableBody>
        </Table>
        {/* 分页 */}
        {/* <Pagination count={10}></Pagination> */}
        <div className="flex justify-center">
            <PaginationComponent
                page={page}
                pageSize={pageSize}
                total={total}
                onChange={(newPage) => setPage(newPage)}
            />
        </div>

        {/* 禁用确认 */}
        <dialog className={`modal ${delShow && 'modal-open'}`}>
            <form method="dialog" className="modal-box w-[360px] bg-[#fff] shadow-lg dark:bg-background">
                <h3 className="font-bold text-lg">{t('prompt')}!</h3>
                <p className="py-4">{t('system.confirmDisable')}</p>
                <div className="modal-action">
                    <Button className="h-8 rounded-full" variant="outline" onClick={close}>{t('cancel')}</Button>
                    <Button className="h-8 rounded-full" variant="destructive" onClick={handleDelete}>{t('disable')}</Button>
                </div>
            </form>
        </dialog>

        <UserRoleModal id={roleOpenId} onClose={() => setRoleOpenId(null)} onChange={handleRoleChange}></UserRoleModal>
    </>
};


const useDelete = () => {
    const [delShow, setDelShow] = useState(false)
    const idRef = useRef<any>(null)

    return {
        delShow,
        idRef,
        close: () => {
            setDelShow(false)
        },
        delConfim: (id) => {
            idRef.current = id
            setDelShow(true)
        }
    }
}