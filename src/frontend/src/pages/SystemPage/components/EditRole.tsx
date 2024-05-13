import { useContext, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "../../../components/bs-ui/button";
import { Input, SearchInput } from "../../../components/bs-ui/input";
import AutoPagination from "../../../components/bs-ui/pagination/autoPagination";
import { Switch } from "../../../components/bs-ui/switch";
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow
} from "../../../components/bs-ui/table";
import { alertContext } from "../../../contexts/alertContext";
import { createRole, getRoleAssistApi, getRoleLibsApi, getRolePermissionsApi, getRoleSkillsApi, updateRoleNameApi, updateRolePermissionsApi } from "../../../controllers/API/user";
import { captureAndAlertRequestErrorHoc } from "../../../controllers/request";
import { useTable } from "../../../util/hook";

const SearchPanne = ({ role_id, title, type, children }) => {
    const { page, pageSize, data, total, loading, setPage, search } = useTable({ pageSize: 10 }, (params) => {
        const { page, pageSize, keyword } = params
        const param = {
            name: keyword,
            role_id,
            page_num: page,
            page_size: pageSize
        }
        return type === 'skill' ? getRoleSkillsApi(param)
            : (type === 'assistant' ? getRoleAssistApi({ ...param, type: 'assistant' })
                : getRoleLibsApi(param))
    })

    return <>
        <div className="mt-20 flex justify-between items-center relative">
            <p className="text-xl font-bold">{title}</p>
            <SearchInput onChange={(e) => search(e.target.value)}></SearchInput>
        </div>
        <div className="mt-4">
            {loading ?
                <div className="w-full h-[468px] flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
                    <span className="loading loading-infinity loading-lg"></span>
                </div>
                : children(data)}
        </div>
        <AutoPagination className="m-0 mt-4 w-auto justify-end" page={page} pageSize={pageSize} total={total} onChange={setPage}></AutoPagination>
    </>
}


// -1 id表示新增
export default function EditRole({ id, name, onChange, onBeforeChange }) {
    const { setErrorData, setSuccessData } = useContext(alertContext);
    const { t } = useTranslation()

    const [form, setForm] = useState({
        name,
        useSkills: [],
        useLibs: [],
        useAssistant: [],
        manageLibs: []
    })
    useEffect(() => {
        if (id !== -1) {
            // 获取详情，初始化选中数据
            getRolePermissionsApi(id).then(res => {
                const useSkills = [], useLibs = [], manageLibs = [], useAssistant = []
                res.data.forEach(item => {
                    switch (item.type) {
                        case 1: useLibs.push(Number(item.third_id)); break;
                        case 2: useSkills.push(item.third_id); break;
                        case 3: manageLibs.push(Number(item.third_id)); break;
                        case 5: useAssistant.push(item.third_id); break;
                    }
                })
                setForm({ name, useSkills, useLibs, useAssistant, manageLibs })
            })
        }
    }, [id])

    const switchDataChange = (id, key, checked) => {
        const index = form[key].findIndex(el => el === id)
        checked && index === -1 && form[key].push(id)
        !checked && index !== -1 && form[key].splice(index, 1)
        setForm({ ...form, [key]: form[key] })
    }

    // 知识库管理权限switch
    const switchLibManage = (id, checked) => {
        switchDataChange(id, 'manageLibs', checked)
        if (checked) switchDataChange(id, 'useLibs', checked)
    }
    // 知识库使用权限switch
    const switchUseLib = (id, checked) => {
        if (!checked && form.manageLibs.includes(id)) return
        switchDataChange(id, 'useLibs', checked)
    }
    /**
     * 保存权限信息
     * 1.验证重名
     * 2.新增时先保存基本信息 创建 ID
     * 3.修改时先更新基本信息
     * 4.批量 保存各个种类权限信息（助手、技能、知识库等）
     * @returns 
     */
    const handleSave = async () => {
        if (!form.name.length || form.name.length > 50) {
            return setErrorData({
                title: t('prompt'),
                list: [t('system.roleNameRequired'), t('system.roleNamePrompt')],
            });
        }
        if (onBeforeChange(form.name)) {
            return setErrorData({
                title: t('prompt'),
                list: [t('system.roleNameExists')]
            })
        }
        // 没有id时需要走创建流程，否则修改
        let roleId = id
        if (id === -1) {
            const res = await captureAndAlertRequestErrorHoc(createRole(form.name))
            roleId = res.id
        } else {
            // 更新基本信息
            captureAndAlertRequestErrorHoc(updateRoleNameApi(roleId, form.name))
        }
        // 更新角色权限
        const res = await Promise.all([
            updateRolePermissionsApi({ role_id: roleId, access_id: form.useSkills, type: 2 }),
            updateRolePermissionsApi({ role_id: roleId, access_id: form.useLibs, type: 1 }),
            updateRolePermissionsApi({ role_id: roleId, access_id: form.manageLibs, type: 3 }),
            updateRolePermissionsApi({ role_id: roleId, access_id: form.useAssistant, type: 5 })
        ])

        console.log('form :>> ', form, res);
        setSuccessData({ title: t('success') })
        onChange(true)
    }

    const roleId = id === -1 ? 0 : id

    return <div className="max-w-[600px] mx-auto pt-4 h-[calc(100vh-136px)] overflow-y-auto pb-10 scrollbar-hide">
        <div className="font-bold mt-4">
            <p className="text-xl mb-4">{t('system.roleName')}</p>
            <Input placeholder={t('system.roleName')} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} maxLength={60}></Input>
        </div>
        {/* 助手 */}
        <div className="">
            <SearchPanne title={t('system.assistantAuthorization')} role_id={roleId} type={'assistant'}>
                {(data) => (
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead>{t('system.assistantName')}</TableHead>
                                <TableHead className="w-[100px]">{t('system.creator')}</TableHead>
                                <TableHead className="text-right">{t('system.usePermission')}</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {data.map((el) => (
                                <TableRow key={el.id}>
                                    <TableCell className="font-medium">{el.name}</TableCell>
                                    <TableCell>{el.user_name}</TableCell>
                                    <TableCell className="text-right">
                                        <Switch checked={form.useAssistant.includes(el.id)} onCheckedChange={(bln) => switchDataChange(el.id, 'useAssistant', bln)} />
                                    </TableCell>
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                )}
            </SearchPanne>
        </div>
        {/* 技能 */}
        <div className="">
            <SearchPanne title={t('system.skillAuthorization')} role_id={roleId} type={'skill'}>
                {(data) => (
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead>{t('system.skillName')}</TableHead>
                                <TableHead className="w-[100px]">{t('system.creator')}</TableHead>
                                <TableHead className="text-right">{t('system.usePermission')}</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {data.map((el) => (
                                <TableRow key={el.id}>
                                    <TableCell className="font-medium">{el.name}</TableCell>
                                    <TableCell>{el.user_name}</TableCell>
                                    <TableCell className="text-right">
                                        <Switch checked={form.useSkills.includes(el.id)} onCheckedChange={(bln) => switchDataChange(el.id, 'useSkills', bln)} />
                                    </TableCell>
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                )}
            </SearchPanne>
        </div>
        {/* 知识库 */}
        <div className="">
            <SearchPanne title={t('system.knowledgeAuthorization')} role_id={roleId} type={'lib'}>
                {(data) => (
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead>{t('lib.libraryName')}</TableHead> 
                                <TableHead className="w-[100px]">{t('system.creator')}</TableHead>
                                <TableHead className="text-right">{t('system.usePermission')}</TableHead>
                                <TableHead className="text-right">{t('system.managePermission')}</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {data.map((el) => (
                                <TableRow key={el.id}>
                                    <TableCell className="font-medium">{el.name}</TableCell>
                                    <TableCell>{el.user_name}</TableCell>
                                    <TableCell className="text-right">
                                        <Switch checked={form.useLibs.includes(el.id)} onCheckedChange={(bln) => switchUseLib(el.id, bln)} />
                                    </TableCell>
                                    <TableCell className="text-right">
                                        <Switch checked={form.manageLibs.includes(el.id)} onCheckedChange={(bln) => switchLibManage(el.id, bln)} />
                                    </TableCell>
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                )}
            </SearchPanne>
        </div>
        <div className="flex justify-center gap-4 mt-16">
            <Button variant="outline" className="px-16" onClick={() => onChange()}>{t('cancel')}</Button>
            <Button className="px-16" onClick={handleSave}>{t('save')}</Button>
        </div>
    </div>
}