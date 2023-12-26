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

export default function Users(params) {
    const [users, setUsers] = useState([])
    const { user } = useContext(userContext);
    const { t } = useTranslation()

    // 分页
    const [page, setPage] = useState(1)
    const [pageEnd, setPageEnd] = useState(false)
    const pages = useRef(0)
    const loadPage = (_page) => {
        // setLoading(true)
        const pageSize = 20
        setPage(_page)
        getUsersApi('', _page, pageSize).then(res => {
            const { data, total } = res.data
            pages.current = Math.ceil(total / pageSize)
            setPageEnd(data.length < pageSize)
            setUsers(data)
            // setLoading(false)
        })
    }
    useEffect(() => {
        loadPage(1)
    }, [])

    // 禁用
    const { delShow, idRef, close, delConfim } = useDelete()
    const handleDelete = () => {
        disableUserApi(idRef.current.user_id, 1).then(res => {
            loadPage(page)
            close()
        })
    }
    const handleEnableUser = (user) => {
        disableUserApi(user.user_id, 0).then(res => {
            loadPage(page)
            close()
        })
    }

    // 编辑
    const [roleOpenId, setRoleOpenId] = useState(null)
    const handleRoleChange = () => {
        setRoleOpenId(null)
        loadPage(page)
    }

    return <>
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
        <div className="join grid grid-cols-2 w-[200px] mx-auto">
            <button disabled={page === 1} className="join-item btn btn-outline btn-xs" onClick={() => loadPage(page - 1)}>{t('previousPage')}</button>
            <button disabled={page >= pages.current || pageEnd} className="join-item btn btn-outline btn-xs" onClick={() => loadPage(page + 1)}>{t('nextPage')}</button>
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