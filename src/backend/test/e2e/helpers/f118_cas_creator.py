"""CAS-only application-creator prerequisite through public Child APIs."""

from dataclasses import dataclass, field

from test.e2e.helpers.auth import auth_headers, get_user_token

CREATOR_MENUS = {"admin", "build", "create_app"}


@dataclass(repr=False)
class CasCreator:
    env: object = field(repr=False)
    role_id: int | None = None
    member_path: str = ""
    department_id: int = 0
    remove_membership: bool = False
    owned_role: bool = False

    async def form(self):
        form = await self.env.ok("GET", self.member_path + "/edit-form", actor=self.env.owner)
        assert form["edit_mode"] == "local_primary" and not form["affiliate_rows"]
        assert form["primary_department"]["id"] == self.department_id
        return {int(rid) for rid in form["primary_department"]["role_ids"]}

    async def install(self):
        env = self.env
        tenant = await env.ok("GET", f"/tenants/{env.tenant_id}", actor=env.owner)
        department = await env.ok("GET", f"/departments/{tenant['root_dept_id']}", actor=env.owner)
        assert department["id"] == tenant["root_dept_id"]
        assert department["name"] == env.prefix + "tenant" and department["parent_id"] == env.parent_id
        self.department_id = department["id"]
        self.member_path = f"/departments/{department['dept_id']}/members/{env.reader_id}"
        before = await self.form()
        roles = await env.ok("GET", f"/departments/{department['dept_id']}/assignable-roles", actor=env.owner)
        choices = []
        for role in roles:
            assert int(role["id"]) > 1, "assignable roles must exclude the system administrator"
            menus = set(await env.ok("GET", f"/roles/{role['id']}/menu", actor=env.owner))
            # Reuse only a minimal creator role, never an unrelated broad role.
            if "create_app" in menus and menus & {"admin", "backend"} and menus <= CREATOR_MENUS | {"backend"}:
                choices.append((len(menus), int(role["id"]), role))
        if choices:
            _, self.role_id, role = min(choices, key=lambda choice: choice[:2])
            self.owned_role = role["role_name"] == env.prefix + "creator"
            if self.owned_role:
                assert role["role_type"] == "tenant" and role["department_id"] == self.department_id
        else:
            role = await env.ok(
                "POST",
                "/roles",
                actor=env.owner,
                json={
                    "role_name": env.prefix + "creator",
                    "department_id": self.department_id,
                    "menu_ids": sorted(CREATOR_MENUS),
                },
            )
            self.role_id = int(role["id"])
            self.owned_role = True
            assert self.role_id > 1 and role["role_type"] == "tenant"
            assert role["role_name"] == env.prefix + "creator" and role["department_id"] == self.department_id
            menus = await env.ok("GET", f"/roles/{self.role_id}/menu", actor=env.owner)
            assert set(menus) == CREATOR_MENUS
        # An exact retained suite role also belongs to this fixture. All other
        # previously assigned roles, including a reused Creator, stay assigned.
        self.remove_membership = self.role_id not in before or self.owned_role
        if self.role_id not in before:
            await env.ok(
                "POST",
                self.member_path + "/apply-edit",
                actor=env.owner,
                json={"primary_role_ids": sorted(before | {self.role_id})},
            )
        assert await self.form() == before | {self.role_id}
        token = await get_user_token(env.client, env.prefix + "reader", env.member_password)
        env.reader = auth_headers(token)
        identity = await env.ok("GET", "/user/info", actor=env.writer)
        assert identity["user_name"] == env.prefix + "reader" and identity["leaf_tenant_id"] == env.tenant_id
        assert identity["role"] != "admin" and not identity["is_child_admin"]
        assert "create_app" in identity["web_menu"], "CAS writer must have effective application creation eligibility"
        assert set(identity["web_menu"]) & {"admin", "backend"}, "application creation requires its effective parent"

    async def cleanup(self):
        if self.role_id is None:
            return
        env = self.env
        if self.remove_membership:
            current = await self.form()
            if self.role_id in current:
                await env.ok(
                    "POST",
                    self.member_path + "/apply-edit",
                    actor=env.owner,
                    json={"primary_role_ids": sorted(current - {self.role_id})},
                )
                assert await self.form() == current - {self.role_id}
        if self.owned_role:
            role = await env.ok("GET", f"/roles/{self.role_id}", actor=env.owner)
            assert role["role_name"] == env.prefix + "creator" and role["role_type"] == "tenant"
            assert role["department_id"] == self.department_id and role["user_count"] == 0
            await env.ok("DELETE", f"/roles/{self.role_id}", actor=env.owner)
        self.role_id = None
