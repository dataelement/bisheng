import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { Button } from "@/components/bs-ui/button";
import { SearchInput } from "@/components/bs-ui/input";
import AutoPagination from "@/components/bs-ui/pagination/autoPagination";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/bs-ui/table";
import { toast } from "@/components/bs-ui/toast/use-toast";
import {
  addTenantUsersApi,
  getTenantUsersApi,
  removeTenantUserApi,
} from "@/controllers/API/tenant";
import { getUsersApi } from "@/controllers/API/user";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import type { Tenant } from "@/types/api/tenant";
import { useTable } from "@/util/hook";
import { useState } from "react";
import { useTranslation } from "react-i18next";

interface Props {
  tenant: Tenant;
  onClose: () => void;
}

export function TenantUserDialog({ tenant, onClose }: Props) {
  const { t } = useTranslation("bs");
  const [addSearch, setAddSearch] = useState("");
  const [addOptions, setAddOptions] = useState<any[]>([]);

  const {
    page,
    pageSize,
    data: users,
    total,
    setPage,
    search,
    reload,
  } = useTable(
    { pageSize: 10 },
    (param: any) =>
      getTenantUsersApi(tenant.id, {
        page: param.page,
        page_size: param.pageSize,
        keyword: param.keyword,
      })
  );

  const searchUsersToAdd = (keyword: string) => {
    setAddSearch(keyword);
    if (keyword.length < 1) {
      setAddOptions([]);
      return;
    }
    captureAndAlertRequestErrorHoc(
      getUsersApi({ page: 1, pageSize: 10, name: keyword }).then(
        (res: any) => {
          setAddOptions(res.data || []);
        }
      )
    );
  };

  const handleAddUser = (user: any) => {
    captureAndAlertRequestErrorHoc(
      addTenantUsersApi(tenant.id, { user_ids: [user.user_id] }).then(() => {
        toast({ title: t("updateSuccess"), variant: "success" });
        setAddSearch("");
        setAddOptions([]);
        reload();
      })
    );
  };

  const handleRemoveUser = (userId: number) => {
    bsConfirm({
      title: t("tenant.removeUser"),
      desc: t("tenant.confirmRemoveUser"),
      onOk: (next: () => void) => {
        captureAndAlertRequestErrorHoc(
          removeTenantUserApi(tenant.id, userId).then(() => {
            toast({ title: t("updateSuccess"), variant: "success" });
            reload();
          })
        );
        next();
      },
    });
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-background rounded-lg p-6 w-[600px] max-h-[80vh] flex flex-col shadow-lg">
        <h3 className="text-lg font-semibold mb-4">
          {t("tenant.users")} - {tenant.tenant_name}
        </h3>

        {/* Add User */}
        <div className="mb-4 relative">
          <input
            className="w-full border rounded px-3 py-2 bg-background"
            placeholder={t("tenant.addUser")}
            value={addSearch}
            onChange={(e) => searchUsersToAdd(e.target.value)}
          />
          {addOptions.length > 0 && (
            <div className="absolute w-full border rounded mt-1 max-h-32 overflow-y-auto bg-background z-10 shadow">
              {addOptions.map((user: any) => (
                <div
                  key={user.user_id}
                  className="px-3 py-2 hover:bg-accent cursor-pointer text-sm"
                  onClick={() => handleAddUser(user)}
                >
                  {user.user_name}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Search */}
        <div className="mb-4">
          <SearchInput
            placeholder={t("tenant.searchUser")}
            onChange={(e: any) => search(e.target.value)}
          />
        </div>

        {/* User List */}
        <div className="flex-1 overflow-y-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("system.username")}</TableHead>
                <TableHead>{t("tenant.lastAccess")}</TableHead>
                <TableHead className="text-right">
                  {t("tenant.actions")}
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {users.map((user: any) => (
                <TableRow key={user.user_id}>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      {user.avatar ? (
                        <img
                          src={user.avatar}
                          alt=""
                          className="w-6 h-6 rounded-full"
                        />
                      ) : (
                        <div className="w-6 h-6 rounded-full bg-primary/10 flex items-center justify-center text-xs">
                          {user.user_name?.charAt(0)}
                        </div>
                      )}
                      {user.user_name}
                    </div>
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {user.join_time
                      ? user.join_time.replace("T", " ").slice(0, 19)
                      : "-"}
                  </TableCell>
                  <TableCell className="text-right">
                    <button
                      className="text-red-500 hover:underline text-sm"
                      onClick={() => handleRemoveUser(user.user_id)}
                    >
                      {t("tenant.removeUser")}
                    </button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>

        <div className="flex items-center justify-between mt-4">
          <AutoPagination
            page={page}
            pageSize={pageSize}
            total={total}
            onChange={(newPage: number) => setPage(newPage)}
          />
          <Button variant="outline" onClick={onClose}>
            {t("close")}
          </Button>
        </div>
      </div>
    </div>
  );
}
