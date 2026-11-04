"""One-off environment preparation for the eval on a BiSheng instance (run on that host).

What it does (idempotent; re-running reuses what exists):
  1. logs in as a tenant admin (RSA password, same as the web UI);
  2. creates plain user `taskmode_eval` and service account `taskmode-eval`, and issues a key
     with chat:invoke + delegate on behalf of that user (admins cannot be delegation targets,
     26007; a service account's own identity cannot be granted skills or knowledge spaces).
     Tasks show up in taskmode_eval's workbench — log in as it to inspect a run;
  3. imports the customer skills used by the selected cases from PACK/skills/*.zip
     (builtin office skills bisheng-docx/pptx/xlsx are NOT imported: they are part of the
     system under test, the environment's own version is used);
  4. as taskmode_eval, creates the two knowledge spaces (eval copies of 106 spaces 9 and 10), uploads the
     files from PACK/knowledge_spaces/<id>/ and waits for parsing;
  5. writes harness/env.json (chmod 600; contains the key).

Usage:
  $PY -I harness/setup_env.py --base-url http://127.0.0.1:7860 --admin admin --password '...' \
      --model 10 --judge-model 16 [--vision-model 1] [--replace-skills]
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
import subprocess
import sys as _sys
import time
from pathlib import Path as _P

import httpx
import rsa

_sys.path.insert(0, str(_P(__file__).resolve().parent))

from common import HARNESS, PACK, dump_json, load_case, load_json, log, select_cases

BUILTIN = {"bisheng-docx", "bisheng-pptx", "bisheng-xlsx", "html-report"}
SKILL_MAP = {"annual-debt-adjustment-local": "annual-debt-adjustment-rag"}
EVAL_USER = "taskmode_eval"
KS_NAMES = {"9": "评测-制度知识空间（106#9）", "10": "评测-研发管理知识空间（106#10）"}


def data(r: httpx.Response):
    body = r.json()
    if r.status_code != 200 or body.get("status_code") != 200:
        raise RuntimeError(
            f"{r.request.method} {r.request.url.path}: HTTP {r.status_code} {body.get('status_code')} {body.get('status_message')}"
        )
    return body.get("data")


def login(base: str, user: str, pw: str) -> httpx.Client:
    c = httpx.Client(base_url=base, timeout=300)
    pk = data(c.get("/api/v1/user/public_key"))["public_key"]
    enc = base64.b64encode(rsa.encrypt(pw.encode(), rsa.PublicKey.load_pkcs1(pk.encode()))).decode()
    d = data(c.post("/api/v1/user/login", json={"user_name": user, "password": enc}))
    if d.get("access_token"):
        c.headers["Authorization"] = f"Bearer {d['access_token']}"
    return c, d.get("user_id")


def mysql(sql: str, args: argparse.Namespace) -> list[list[str]]:
    """Run a read query against the platform database (pymysql; works on hosts without a mysql client)."""
    import urllib.parse

    import pymysql

    u = urllib.parse.urlparse(args.db_url.replace("mysql+pymysql://", "mysql://"))
    conn = pymysql.connect(
        host=u.hostname,
        port=u.port or 3306,
        user=urllib.parse.unquote(u.username or ""),
        password=urllib.parse.unquote(u.password or ""),
        database=u.path.lstrip("/"),
        charset="utf8mb4",
    )
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            return [["" if v is None else str(v) for v in row] for row in cur.fetchall()]
    finally:
        conn.close()


def bind_management_tenant(c: httpx.Client, tenant_id: int) -> None:
    """Super admins must pick a management tenant before management writes (26073 otherwise)."""
    scope = data(c.get("/api/v1/service-accounts/management-scope")) or {}
    current = scope.get("tenant_id") or scope.get("selected_tenant_id")
    if current != tenant_id:
        data(c.put("/api/v1/service-accounts/management-scope", json={"tenant_id": tenant_id}))
    c.headers["X-Management-Tenant"] = str(tenant_id)
    c.headers["X-Service-Account-Tenant"] = str(tenant_id)


def ensure_eval_user(c: httpx.Client, args, known_pw: str | None) -> tuple[int, str]:
    """A plain (non-admin) user the key acts for; admins cannot be delegation targets (26007)."""
    rows = mysql(f"select user_id from user where user_name='{EVAL_USER}' and `delete`=0", args)
    pw = args.eval_user_password or known_pw
    if not rows:
        pw = pw or "Ev@" + secrets.token_urlsafe(12)
        pk = data(c.get("/api/v1/user/public_key"))["public_key"]
        enc = base64.b64encode(rsa.encrypt(pw.encode(), rsa.PublicKey.load_pkcs1(pk.encode()))).decode()
        data(c.post("/api/v1/user/create", json={"user_name": EVAL_USER, "password": enc}))
        rows = mysql(f"select user_id from user where user_name='{EVAL_USER}' and `delete`=0", args)
        log(f"已建评测用户 {EVAL_USER} id={rows[0][0]}")
    # First login binds the user to its tenant (user_tenant); delegation requires that row.
    login(args.base_url, EVAL_USER, pw)
    return int(rows[0][0]), pw


def ensure_key(c: httpx.Client, admin_id: int, eval_user_id: int) -> str:
    page = data(c.get("/api/v1/service-accounts", params={"page": 1, "page_size": 100, "keyword": "taskmode-eval"}))
    items = page.get("data") or page.get("items") or []
    sa = next((s for s in items if s.get("name") == "taskmode-eval"), None)
    if sa is None:
        sa = data(
            c.post(
                "/api/v1/service-accounts",
                json={
                    "name": "taskmode-eval",
                    "description": "任务模式评测集执行器",
                    "resource_owner_user_id": admin_id,
                },
            )
        )
        log(f"已建服务账号 taskmode-eval id={sa['id']}")
    data(c.post(f"/api/v1/service-accounts/{sa['id']}/keys/revoke-all"))  # the old plaintext is unrecoverable anyway
    issued = data(
        c.post(
            f"/api/v1/service-accounts/{sa['id']}/keys",
            json={
                "name": f"eval-{time.strftime('%Y%m%d%H%M')}",
                "scopes": ["chat:invoke", "delegate"],
                "delegate_scopes": [{"subject_type": "user", "subject_id": eval_user_id}],
            },
        )
    )
    key = issued.get("plaintext")
    if not key:
        raise RuntimeError(f"签发密钥的返回里找不到明文：{list(issued)}")
    log(f"已签发密钥 {issued.get('name') or ''}（服务账号 {sa['id']}）")
    return key


def ensure_skills(c: httpx.Client, needed: set[str], replace: bool) -> None:
    def exists(name: str) -> bool:
        d = data(c.get("/api/v1/linsight/skill", params={"keyword": name, "page": 1, "page_size": 100}))
        rows = d if isinstance(d, list) else (d.get("data") or d.get("items") or d.get("list") or [])
        return any(isinstance(r, dict) and r.get("name") == name for r in rows)

    existing = {n for n in needed - BUILTIN if exists(n)}
    for name in sorted(needed - BUILTIN):
        z = PACK / "skills" / f"{name}.zip"
        if not z.exists():
            log(f"技能包缺失：{z}")
            continue
        if name in existing and not replace:
            log(f"技能 {name} 已存在，保留环境里的版本（要换成材料包版本加 --replace-skills）")
            continue
        with open(z, "rb") as f:
            files = {"file": (z.name, f, "application/zip")}
            if name in existing:
                data(c.put(f"/api/v1/linsight/skill/{name}", files=files))
                log(f"技能 {name} 已用材料包版本覆盖")
            else:
                data(c.post("/api/v1/linsight/skill", files=files))
                log(f"技能 {name} 已导入")
        try:
            data(c.patch(f"/api/v1/linsight/skill/{name}/status", json={"enabled": True}))
        except Exception as e:
            log(f"启用技能 {name}：{e}")


def ensure_spaces(c: httpx.Client, needed: set[str], args) -> dict:
    mapping = {}
    for src in sorted(needed):
        name = KS_NAMES.get(src, f"评测-知识空间（106#{src}）")
        rows = mysql(f"select id from knowledge where name='{name}' and type=3 order by id desc limit 1", args)
        if rows:
            ks_id = int(rows[0][0])
            log(f"知识空间已存在：{name} id={ks_id}")
        else:
            ks_id = int(
                data(
                    c.post(
                        "/api/v1/knowledge/space",
                        json={"name": name, "description": "任务模式评测集用，勿改动", "is_released": True},
                    )
                )["id"]
            )
            log(f"已建知识空间 {name} id={ks_id}")
        have = {r[0] for r in mysql(f"select file_name from knowledgefile where knowledge_id={ks_id}", args)}
        paths = []
        for p in sorted((PACK / "knowledge_spaces" / src).iterdir()):
            if p.name in have:
                continue
            with open(p, "rb") as f:
                paths.append(data(c.post("/api/v1/knowledge/upload", files={"file": (p.name, f)}))["file_path"])
        if paths:
            data(c.post(f"/api/v1/knowledge/space/{ks_id}/files", json={"file_path": paths}))
            log(f"{name}：上传 {len(paths)} 个文件，等待解析")
        for _ in range(180):
            st = mysql(f"select status,count(*) from knowledgefile where knowledge_id={ks_id} group by status", args)
            pending = sum(int(n) for s, n in st if s in ("1", "4", "5"))
            if not pending:
                break
            time.sleep(10)
        log(f"{name} 解析状态：{dict((s, int(n)) for s, n in st)}（2=成功，3=失败）")
        mapping[src] = ks_id
    return mapping


def judge_cfg(model_id: str, args) -> dict:
    rows = mysql(
        f"select l.model_name,s.config from llm_model l join llm_server s on s.id=l.server_id where l.id={int(model_id)}",
        args,
    )
    name, cfg = rows[0][0], json.loads(rows[0][1])
    base = cfg.get("openai_api_base") or cfg.get("base_url")
    key = (cfg.get("openai_api_key") or cfg.get("api_key") or "").strip()
    extra = {"enable_thinking": False} if "dashscope" in (base or "") else {}
    return {"base_url": base, "api_key": key, "model": name, "extra_body": extra, "bisheng_model_id": str(model_id)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:7860")
    ap.add_argument("--admin", default="admin")
    ap.add_argument("--password", required=True)
    ap.add_argument("--model", required=True, help="被测模型 id（本环境的 llm_model.id）")
    ap.add_argument("--vision-model", default=None, help="读图用例 B12 用的模型 id")
    ap.add_argument("--judge-model", required=True, help="评审模型 id；建议与被测模型不同家族")
    ap.add_argument("--replace-skills", action="store_true")
    ap.add_argument("--tenant-id", type=int, default=1)
    ap.add_argument(
        "--eval-user-password",
        default=None,
        help="评测用户 taskmode_eval 的登录密码；首次创建时不填则随机生成，之后从 env.json 读取",
    )
    ap.add_argument("--skip-spaces", action="store_true", help="先不建知识空间（建空间会把制度文件送去解析和向量化）")
    ap.add_argument(
        "--platform-version",
        default=None,
        help="记进 env.json 的被测版本标识，如镜像 digest；默认取 /opt/bisheng 的 git HEAD",
    )
    ap.add_argument(
        "--db-url",
        default=os.environ.get("DB_URL") or "mysql://bisheng:123456@127.0.0.1:3306/bisheng",
        help="平台数据库连接串，只用于读：查已有用户/知识空间、文件解析状态、评审模型凭据",
    )
    args = ap.parse_args()

    c, admin_id = login(args.base_url, args.admin, args.password)
    admin_id = admin_id or 1
    bind_management_tenant(c, args.tenant_id)
    cases = select_cases("all")
    skills, spaces = set(), set()
    for sel in cases:
        case, _ = load_case(sel["id"])
        skills |= {SKILL_MAP.get(s, s) for s in case.get("skills") or []}
        spaces |= {str(k) for k in case.get("knowledge_space_ids") or []}

    env_path = HARNESS / "env.json"
    env = load_json(env_path, {}) or {}
    eval_user_id, eval_pw = ensure_eval_user(c, args, (env.get("eval_user") or {}).get("password"))
    if not eval_pw:
        raise SystemExit(f"{EVAL_USER} 已存在但不知道密码：用 --eval-user-password 传入")
    env["eval_user"] = {"user_name": EVAL_USER, "user_id": eval_user_id, "password": eval_pw}
    if not env.get("api_key") or str(env.get("on_behalf_of")) != str(eval_user_id):
        env["api_key"] = ensure_key(c, admin_id, eval_user_id)
        env["on_behalf_of"] = str(eval_user_id)
        env.pop("end_user", None)
        dump_json(env_path, env)  # persist at once: the plaintext is shown only once
    ensure_skills(c, skills, args.replace_skills)
    # Spaces are created by the eval user so it owns them (no membership grants needed).
    u, _ = login(args.base_url, EVAL_USER, eval_pw)
    env.update(
        {
            "base_url": args.base_url,
            "model": str(args.model),
            "model_overrides": {"B12": str(args.vision_model)} if args.vision_model else {},
            "skill_map": SKILL_MAP,
            "knowledge_space_map": env.get("knowledge_space_map", {})
            if args.skip_spaces
            else ensure_spaces(u, spaces, args),
            "case_timeout_min": 90,
            "judge": judge_cfg(args.judge_model, args),
        }
    )
    env["platform_version"] = args.platform_version or (
        subprocess.run(
            ["git", "-C", "/opt/bisheng", "rev-parse", "--short", "HEAD"], capture_output=True, text=True
        ).stdout.strip()
        or None
    )
    dump_json(env_path, env)
    log(f"已写 {env_path}（含密钥，权限 600）")


if __name__ == "__main__":
    main()
