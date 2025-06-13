import { Badge } from "@/components/bs-ui/badge";
import { Button } from "@/components/bs-ui/button";
import { Checkbox } from "@/components/bs-ui/checkBox";
import { Label } from "@/components/bs-ui/label";
import { Select, SelectContent, SelectTrigger } from "@/components/bs-ui/select";
import { getUserGroupTreeApi, getUserGroupUsersApi } from "@/controllers/API/user";
import { ChevronRight, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useQuery } from "react-query";

// by ai
const useGroupUsers = (checkedUsers, setCheckedUsers) => {
    const [users, setUsers] = useState([]);
    const [depAllUsers, setAllUsers] = useState([]); // 保存所有用户数据
    const depUsersRef = useRef([]); // 当前部门所有用户
    const allUsersRef = useRef([]); // 所有用户
    const [page, setPage] = useState(1);
    const [totalUsers, setTotalUsers] = useState(0);
    const currentGroupIdRef = useRef('');

    // 获取用户列表并保存所有用户数据
    const getGroupUsers = async (groupId) => {
        currentGroupIdRef.current = groupId;
        const res = await getUserGroupUsersApi(groupId);  // 假设服务端返回了所有用户
        updateUsers(res.data, groupId)
    };

    const updateUsers = (users, groupId) => {
        allUsersRef.current = users;
        const depUsers = users.filter(user => user.group_ids?.includes(groupId));
        setAllUsers(depUsers); // 保存所有用户
        depUsersRef.current = depUsers;
        setTotalUsers(depUsers.length);
    }

    // 计算当前页需要显示的用户
    const getPaginatedUsers = () => {
        const startIndex = (page - 1) * 10; // 每页显示10个用户
        const endIndex = startIndex + 10;
        return depAllUsers.slice(startIndex, endIndex); // 截取当前页的数据
    };

    // 计算是否是第一页和最后一页
    const isFirstPage = page === 1;
    const isLastPage = page * 10 >= totalUsers;

    // 获取分页后的用户
    useEffect(() => {
        setUsers(getPaginatedUsers()); // 每次页码变化时更新显示的用户
    }, [page, depAllUsers]); // 依赖页码和所有用户数据

    // 上一页和下一页按钮点击处理
    const handlePaginationChange = (direction) => {
        const newPage = direction === 'next' ? page + 1 : page - 1;
        setPage(newPage);
        // 不需要重新加载用户，只更新当前页显示的用户
        getGroupUsers(value.id);
    };

    const checkUsers = async (checked, groupId) => {
        if (currentGroupIdRef.current === groupId) {
            if (checked) {
                // 选中所有用户
                setCheckedUsers(new Set(depAllUsers.map(user => user.user_id)));
            } else {
                // 取消选中所有用户，但保留其他用户组的选中状态
                const remainingCheckedUsers = Array.from(checkedUsers).filter(userId =>
                    // 保留已经选中的属于其他部门的用户
                    !depAllUsers.some(user => user.user_id === userId)
                );
                setCheckedUsers(new Set(remainingCheckedUsers)); // 更新为只保留当前用户组之外的选中用户
            }
            return;
        }
        // 获取当前用户组的用户数据
        const res = await getUserGroupUsersApi(groupId);
        updateUsers(res.data, groupId)

        if (checked) {
            // 选中当前用户组的所有用户
            setCheckedUsers(new Set(res.data.map(user => user.user_id)));
        } else {
            // 取消选中当前用户组的所有用户，但保留其他选中状态的用户
            const remainingCheckedUsers = Array.from(checkedUsers).filter(userId =>
                !res.data.some(user => user.user_id === userId) // 保留选中的不在当前组中的用户
            );
            setCheckedUsers(new Set(remainingCheckedUsers)); // 更新为只保留当前用户组之外的选中用户
        }
    };


    return {
        users, // 当前页的用户
        getGroupUsers,
        page,
        allUsersRef,
        setPage,
        totalUsers,
        isFirstPage,  // 是否是第一页
        isLastPage,   // 是否是最后一页
        handlePaginationChange, // 处理分页按钮点击
        checkUsers
    };
};

const SelectUserByGroup = ({ groupId, value, onChange }) => {
    const [open, setOpen] = useState(false);
    const [expandedNodes, setExpandedNodes] = useState(new Set());
    const [checkedGroups, setCheckedGroups] = useState(new Set()); // 存储选中的用户组
    const [checkedUsers, setCheckedUsers] = useState(new Set()); // 存储选中的用户
    const initChangeRef = useRef(false);

    const { data: options = [], refetch: refetchGroupTree } = useQuery({
        queryKey: ["QueryGroupTreeKey", groupId],
        queryFn: () => getUserGroupTreeApi(groupId),
    });

    // useEffect(() => {
    //     // 仅在value变化时更新checkedUsers，不触发onChange
    //     if (value.length) {
    //         const initialCheckedUsers = new Set(value.map(user => user.user_id));
    //         setCheckedUsers(initialCheckedUsers); // 初始化checkedUsers
    //         initChangeRef.current = true;
    //     }
    // }, [value]);

    const { allUsersRef, users, getGroupUsers, checkUsers, page, setPage, totalUsers, isFirstPage, isLastPage } = useGroupUsers(checkedUsers, setCheckedUsers);

    // 渲染树形结构并处理checkbox的级联选择
    const renderTree = (nodes, level = 0) => {
        return nodes.map((node) => {
            const isExpanded = expandedNodes.has(node.id);
            const isSelected = checkedGroups.has(node.id); // 用户组选中状态
            const isIndeterminate = !isSelected && node.children?.some(child => checkedUsers.has(child.id)); // 半选状态

            return (
                <div key={node.id} className="pl-2">
                    <div
                        className={`relative flex items-center gap-2 cursor-pointer ${isSelected ? 'bg-blue-200' : ''} hover:bg-blue-100 rounded-md p-1 py-2`}
                        onClick={() => getGroupUsers(node.id)} // 点击用户组加载用户
                    >
                        {node.children?.length > 0 && (
                            <ChevronRight
                                size={18}
                                className={`absolute -left-4 cursor-pointer ${isExpanded ? 'rotate-90' : ''}`}
                                onClick={(e) => {
                                    e.stopPropagation(); // 阻止事件冒泡
                                    setExpandedNodes(prev =>
                                        isExpanded ? new Set([...prev].filter(id => id !== node.id)) : new Set([...prev, node.id])
                                    );
                                }}
                            />
                        )}
                        <Checkbox
                            checked={isIndeterminate ? 'indeterminate' : isSelected}
                            onClick={(e) => e.stopPropagation()}
                            onCheckedChange={(checked) => handleGroupCheckboxChange(node, checked)} // 用户组checkbox的级联逻辑
                        />
                        <Label>{node.group_name}</Label>
                    </div>
                    {isExpanded && node.children && (
                        <div className="pl-4">{renderTree(node.children, level + 1)}</div>
                    )}
                </div>
            );
        });
    };

    // 递归更新所有子用户组的选中状态
    const updateCheckedGroups = (node, checked) => {
        setCheckedGroups(prev => {
            const updated = new Set(prev);
            if (checked) {
                updated.add(node.id);
            } else {
                updated.delete(node.id);
            }
            return updated;
        });

        if (node.children && node.children.length > 0) {
            node.children.forEach(child => {
                updateCheckedGroups(child, checked);
            });
        }
    };

    // 处理用户组checkbox的级联逻辑
    const handleGroupCheckboxChange = (node, checked) => {
        updateCheckedGroups(node, checked);
        checkUsers(checked, node.id);
    };

    // 处理用户选择
    const handleUserSelection = (userId, checked) => {
        const selectedUsers = new Set(checkedUsers);
        if (checked) {
            selectedUsers.add(userId);
        } else {
            selectedUsers.delete(userId);
        }
        setCheckedUsers(selectedUsers);
    };

    useEffect(() => {
        // if (initChangeRef.current) {
        //     initChangeRef.current = false;
        //     return;
        // }
        // 找到用户的真实名字并构造返回的数据
        const selectedUsersData = Array.from(checkedUsers).map(id => {
            const user = allUsersRef.current.find(user => user.user_id === id);  // 查找用户对象
            return user ? { user_id: user.user_id, user_name: user.user_name } : null; // 返回真实的用户名
        }).filter(user => user !== null);  // 过滤掉为 null 的项

        onChange(selectedUsersData); // 传递数据给父组件
    }, [checkedUsers]);

    // 处理分页按钮点击
    const handlePaginationChange = (direction) => {
        const newPage = direction === 'next' ? page + 1 : page - 1;
        setPage(newPage);
    };

    // 删除用户
    const handleBadgeRemove = (e, userId) => {
        console.log('userid :>> ', userId);
        e.stopPropagation()
        const updatedCheckedUsers = new Set(checkedUsers);
        updatedCheckedUsers.delete(userId);
        setCheckedUsers(updatedCheckedUsers);
    };

    return (
        <Select open={open} onOpenChange={setOpen}>
            <SelectTrigger>
                <div className="max-h-8 overflow-y-auto overflow-x-hidden break-all flex flex-wrap gap-1">
                    {value.map(item => (
                        <Badge variant="gray" className="relative" key={item.user_id}
                            onPointerDown={(e) => e.stopPropagation()}
                        >
                            {item.user_name}
                            {/* <X
                                size={14}
                                className="cursor-pointer "
                                onClick={(e) => handleBadgeRemove(e, item.user_id)} // 点击删除按钮
                            /> */}
                        </Badge>
                    ))}
                </div>
            </SelectTrigger>
            <SelectContent position="popper" avoidCollisions={false}>
                <div className="grid grid-cols-2 max-w-[580px]">
                    <div className="border-l first:border-none max-h-72 overflow-auto">
                        <div className="p-2">{renderTree(options)}</div>
                    </div>
                    <div className="relative border-l p-2 max-h-72 overflow-y-auto">
                        {users.map(user => (
                            <div key={user.user_id} className="flex items-center gap-2 mb-2">
                                <Checkbox
                                    checked={checkedUsers.has(user.user_id)}
                                    onCheckedChange={(checked) => handleUserSelection(user.user_id, checked)}
                                />
                                <Label>{user.user_name}</Label>
                            </div>
                        ))}
                        <div className="absolute bottom-0 right-2 flex justify-between gap-2 mt-2">
                            <Button className="h-6 text-xs" disabled={isFirstPage} onClick={() => handlePaginationChange('prev')}>上一页</Button>
                            <Button className="h-6 text-xs" disabled={isLastPage} onClick={() => handlePaginationChange('next')}>下一页</Button>
                        </div>
                    </div>
                </div>
            </SelectContent>
        </Select>
    );
};

export default SelectUserByGroup;
