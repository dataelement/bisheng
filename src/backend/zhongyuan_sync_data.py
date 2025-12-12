import asyncio,requests,jwt,time,uuid,base64,rsa,os,datetime,sys
from fastapi import Request, HTTPException
from typing import Dict, List, Optional, Any
from bisheng.api.services.role_group_service import RoleGroupService
from bisheng.api.services.user_service import UserPayload, UserService
from bisheng.database.models.group import GroupCreate
from bisheng.database.models.zhongyuan_group import ZhongYuanGroupDao, ZhongYuanGroupCreate
from bisheng.api.v1.usergroup import get_group_roles
from bisheng.api.v1.user import create_role, access_refresh, delete_role, get_rsa_publish_key, update
from bisheng.database.models.user import UserUpdate
from bisheng.database.models.role import RoleCreate
from bisheng.database.models.role_access import RoleRefresh
from bisheng.database.models.zhongyuan_role import ZhongYuanRoleDao, ZhongYuanRoleCreate
from bisheng.api.v1.schemas import CreateUserReq, GroupAndRoles
from datetime import datetime as dt


async def mock_receive():
    return {"type": "http.request", "body": b""}
async def mock_send(_):
    pass
def get_mock_request():
    scope = {
        "type": "http",
        "headers": [(b"x-forwarded-for", b"localhost")]
    }
    return Request(scope=scope, receive=mock_receive, send=mock_send)

request = get_mock_request()
login_user = UserPayload(user_id=1)
TIME_OFFSET_SECONDS = 0

BASE_URL = "https://iamqr.zyxt.com.cn"
APP_ID = "425bc6444b054b77"
APP_SECRET = "722c20b9289d48fb96fce5abfe6484d1"
current_log_file = None
native_print = print

"""生成新的日志文件路径（每次sync_task执行时调用）"""
def generate_new_log_file():
    global current_log_file
    current_time = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    current_log_file = f"sync_logs/log_{current_time}.txt"
    # 初始化新日志文件（创建空文件）
    with open(current_log_file, 'w', encoding='utf-8') as f:
        f.write(f"===== 同步任务日志 - {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} =====\n")
    print(f"已创建新日志文件：{current_log_file}")

"""自定义打印函数：1. 输出到终端2. 追加到当前日志文件（每次sync_task绑定新文件）"""
def log_print(*args, **kwargs):
    # 1. 使用原生print输出到终端
    native_print(*args, **kwargs)
    # 2. 输出到日志文件（追加模式）
    if not current_log_file:
        generate_new_log_file()  # 兜底：如果未初始化则生成新文件
    # 3.处理打印参数
    end = kwargs.get('end', '\n')
    sep = kwargs.get('sep', ' ')
    # 4.将参数转换为字符串
    log_content = sep.join(map(str, args)) + end
    # 5.写入文件（使用a模式追加）
    try:
        with open(current_log_file, 'a', encoding='utf-8') as f:
            f.write(log_content)
    except Exception as e:
        # 日志写入失败时仅在终端提示（使用原生print）
        native_print(f"【日志写入失败】：{str(e)}")
print = log_print

def get_token() -> str:
    """生成Bearer JWT Token"""
    local_request_time_ms = int(time.time() * 1000)
    current_time_seconds = int(local_request_time_ms / 1000)
    issued_at_time = current_time_seconds + TIME_OFFSET_SECONDS
    payload = {"iss": APP_ID, "jti": str(uuid.uuid4()), "iat": issued_at_time}
    token = jwt.encode(payload, APP_SECRET.encode('utf-8'), algorithm="HS256")
    return f"Bearer {token}"

# 获取组织编码-分组ID映射  org_code --> group_id
def get_org_code_to_group_id_mapping() -> Dict[str, int]:
    org_code_group_mapping = {}
    try:
        all_zhongyuan = ZhongYuanGroupDao.get_all_group()
        for item in all_zhongyuan:
            if item.org_code and item.group_id:
                org_code_group_mapping[item.org_code] = item.group_id
        print(f"读取到 {len(org_code_group_mapping)} 条组织编码-分组ID映射")
    except Exception as e:
        print(f"读取组织编码映射失败：{str(e)}")
    return org_code_group_mapping


# 一.1.获取组织数据
# 组织数据样例
'''
{ 
    "idt_org__status": 1,
    "request_log__id": "2252742099445282983",
    "idt_org__id": "1992892519293149827",
    "idt_org__name": "公司领导",
    "request_log__action_desc": "管理员操作-重新执行组织供应策略",
    "idt_org__sup_org_code": "gs1",
    "idt_org__org_code": "1",
    "request_log__action_flag": 0
}
'''
def get_all_org_data() -> list[dict]:
    """获取所有组织原始数据（每页20条）"""
    endpoint = "/esc-idm/api/v1/org/list"
    page_size = 20
    current_page = 1
    all_orgs = []
    while True:
        body = {"size": str(page_size), "page": str(current_page), "startTime": ""}
        headers = {"Content-Type": "application/json", "Authorization": get_token()}
        try:
            # 1.发送请求
            resp = requests.post(BASE_URL + endpoint, headers=headers, json=body, timeout=15)
            resp.raise_for_status()  # 抛出HTTP错误
            result = resp.json()
            # 2.检查响应码
            if result.get("code") != "0":
                print(f"第{current_page}页获取失败: {result.get('message')}")
                break
            data = result["data"]
            current_list = data["list"]
            total = int(data["total"])
            # 3.提取组织数据（保留原始字段名）
            for org in current_list:
                all_orgs.append(org)
            print(f"已获取第{current_page}页，累计{len(all_orgs)}/{total}条")
            if len(all_orgs) >= total:
                break
            current_page += 1
        except requests.exceptions.Timeout:
            print(f"第{current_page}页请求超时")
            break
        except requests.exceptions.HTTPError as e:
            print(f"第{current_page}页HTTP错误: {e}")
            break
        except Exception as e:
            print(f"第{current_page}页请求异常: {str(e)}")
            break
    
    # 排序逻辑：按org_code数字降序，非数字放前面，gs1放最后
    org_list_flat = sorted(all_orgs, key=lambda x: int(x["idt_org__org_code"]) if x["idt_org__org_code"].isdigit() else (-1 if x["idt_org__org_code"] != "gs1" else float('inf')), reverse=True)
    # 将gs1(中原信托有限公司)移到最后
    if org_list_flat:
        # 找到gs1的位置并移到最后
        gs1_index = -1
        for i, org in enumerate(org_list_flat):
            if org.get("idt_org__org_code") == "gs1":
                gs1_index = i
                break
        if gs1_index != -1:
            org_list_flat.append(org_list_flat.pop(gs1_index))
    
    for org in org_list_flat:
        print(org)
    return org_list_flat

# 一.2. 创建分组
def create_group_by_name(group_name: str) -> Optional[int]:
    group_create = GroupCreate(group_name=group_name,remark=f"同步的组：{group_name}")
    try:
        group = RoleGroupService().create_group(request, login_user, group_create)
        print(f"分组「{group_name}」创建成功！,创建的分组id是：{group.id}")
        return group.id
    except Exception as e:
        print(f"分组「{group_name}」创建失败：{str(e)}")
        return None
# 一.3. 保存组织信息到zhongyuan_group表
def save_org_to_zhongyuan_group(org_info: Dict, group_id: int):
    """
    保存组织信息到zhongyuan_group表（使用原始字段名映射到表字段）
    """
    try:
        zhongyuan_create = ZhongYuanGroupCreate(
            group_id=group_id,
            org_id=org_info["idt_org__id"],  # 原始字段
            org_code=org_info["idt_org__org_code"],  # 原始字段
            sup_org_code=org_info["idt_org__sup_org_code"],  # 原始字段
            org_status=org_info["idt_org__status"],  # 原始字段
            org_name=org_info["idt_org__name"],  # 原始字段
            full_org_name=org_info["idt_org__name"],  # 使用名称作为完整名称
            remark=f"关联分组ID {group_id}：{org_info['idt_org__name']}（原始ID：{org_info['idt_org__id']}）"
        )
        ZhongYuanGroupDao.insert_group(zhongyuan_create)
        print(f"组织 {org_info['idt_org__id']}（{org_info['idt_org__name']}）关联分组 {group_id} 已存入zhongyuan_group表")
    except Exception as e:
        print(f"组织 {org_info['idt_org__id']} 存入数据库失败：{str(e)}")

# 一.同步-组织数据
async def sync_group_data():
    print("开始读取数据库中已存在的组织数据ord_id -- bisheng分组group_id的映射...")
    existing_org_mappings = {}
    try:
        all_zhongyuan = ZhongYuanGroupDao.get_all_group()
        for item in all_zhongyuan:
            existing_org_mappings[item.org_id] = item.group_id
        print(f"读取到 {len(existing_org_mappings)} 条已存在的组织映射记录")
    except Exception as e:
        print(f"读取数据库失败：{str(e)}")
        return
    print("1.开始获取组织数据...")
    org_list_flat = get_all_org_data()  # 获取原始组织数据
    if not org_list_flat:
        print("未获取到任何组织数据")
        return
    
    print("2.开始按排序顺序处理分组...")
    existed_count = 0
    created_count = 0
    fail_count = 0
    # 3.创建分组
    for org in org_list_flat:
        # 3.0.获取组织ID
        org_id = org.get("idt_org__id")
        if not org_id:
            print(f"组织 {org.get('idt_org__name', '未知名称')} 无有效ID，跳过")
            fail_count += 1
            continue
        # 3.1.检查是否已存在---已存在
        if org_id in existing_org_mappings:
            group_id = existing_org_mappings[org_id]
            print(f"组织 {org_id}（{org['idt_org__name']}）已存在，对应分组ID：{group_id}")
            existed_count += 1
            continue

        # 3.2.组织不存在
        org_name = org.get("idt_org__name", f"未知组织-{org_id}")
        group_id = create_group_by_name(org_name)
        if group_id:
            # 保存到数据库
            save_org_to_zhongyuan_group(org, group_id)
            created_count += 1
            
            # 仅在组织不存在且是gs1组织时创建全局默认角色
            if org.get("idt_org__org_code") == "gs1":
                try:
                    print(f"\n开始为gs1组织（分组ID：{group_id}）创建全局默认角色...")
                    role_name = f'组织-角色'
                    role = RoleCreate(role_name=role_name, group_id=group_id)
                    resp = await create_role(request=request, role=role, login_user=login_user)
                    
                    if resp.status_code == 200 and hasattr(resp.data, 'id'):
                        role_id = resp.data.id
                        print(f"全局默认角色创建成功：ID={role_id}")
                    else:
                        raise Exception(f"全局默认角色创建失败，响应码：{resp.status_code}")
                    # 配置角色权限
                    if role_id:
                        print(f"配置全局默认角色 {role_id} 权限...")
                        role_refresh = RoleRefresh(role_id=role_id, access_id=['build', 'knowledge'], type=99)
                        resp = await access_refresh(request=request, data=role_refresh, login_user=login_user)
                        
                        if resp.status_code != 200:
                            raise Exception(f"全局默认角色权限配置失败，响应码：{resp.status_code}")
                        print(f"全局默认角色 {role_id} 权限配置成功")
                except Exception as e:
                    print(f"创建gs1组织全局默认角色失败：{str(e)}")
        else:
            print(f"组织 {org_id}（{org_name}）分组创建失败")
            fail_count += 1
    
    # 输出统计信息
    print(f"统计：")
    print(f"   - 已存在无需创建：{existed_count} 个")
    print(f"   - 新创建成功：{created_count} 个")
    print(f"   - 处理失败：{fail_count} 个")
    print(f"   - 总计处理组织：{len(org_list_flat)} 个")


# 二.1.获取用户数据
# 用户数据样例如下:
'''
{
   'app_account__update_time': '2025-12-02 16:56:20', 
   'app_account__status': 1, 
   'app_account__id': '2252742099445283223', 
   'useTypes': [], 
   'request_log__id': '2252742099445283224', 
   'jobs': [], 
   'app_account__account_uuid': 
   'cd6fb579-4dbb-413d-be32-d576271af106', 
   'request_log__action_desc': '管理员操作-重新执行帐号供应策略(立即生效)', 
   'orgs': [{
      'idt_org__name': '第一财富中心市场二部', 
      'idt_org__sup_org_code': '11', 
      'idt_org__org_code': '27'
    }], 
   'app_account__account_no': 'zhangn', 
   'app_account__account_name': '张宁', 
   'request_log__action_flag': 0
}
'''
def get_all_user_data() -> list[dict]:
    """获取所有用户原始数据（每页20条，统一分页逻辑）"""
    endpoint = "/esc-idm/api/v1/account/list"
    page_size = 20
    current_page = 1
    all_users = []
    
    print(f"开始获取用户数据，每页{page_size}条...")
    print(f"请求地址：{BASE_URL}{endpoint}")
    
    while True:
        body = {"size": str(page_size), "page": str(current_page), "startTime": ""}
        headers = {"Content-Type": "application/json", "Authorization": get_token()}
        try:
            # 1.发送请求
            resp = requests.post(BASE_URL + endpoint, headers=headers, json=body, timeout=15)
            resp.raise_for_status()  # 抛出HTTP错误
            result = resp.json()
            # 2.检查响应码
            if result.get("code") != "0":
                print(f"第{current_page}页获取失败: {result.get('message')}")
                break
            # 3.解析响应数据
            data = result["data"]
            current_list = data["list"]
            total = int(data["total"])
            # 4.提取核心字段，结构化存储
            for user in current_list:
                all_users.append(user)
            # 5.打印进度
            print(f"第{current_page}页获取成功，当前累计{len(all_users)}/{total}条")
            # 6.终止条件判断
            if len(all_users) >= total:
                print(f"所有用户数据获取完成，共{len(all_users)}条")
                break
            current_page += 1
        except requests.exceptions.Timeout:
            print(f"第{current_page}页请求超时")
            break
        except requests.exceptions.HTTPError as e:
            print(f"第{current_page}页HTTP错误: {e}")
            break
        except Exception as e:
            print(f"第{current_page}页请求异常: {str(e)}")
            break
    
    # ===================== 开始去重逻辑（直接写在函数内） =====================
    print("\n开始执行去重操作...")
    # 解析时间字符串为时间戳的内部函数
    def _parse_update_time(time_str: str) -> float:
        try:
            dt_obj = dt.strptime(time_str, "%Y-%m-%d %H:%M:%S")
            return dt_obj.timestamp()
        except (ValueError, TypeError):
            return 0.0
    
    user_dict = {}  # key: app_account__id, value: 用户数据
    duplicate_records = []  # 存储重复的记录信息
    duplicate_count = 0     # 重复记录总数
    
    for user in all_users:
        user_id = user.get("app_account__id")
        if not user_id:
            print(f"警告：发现无app_account__id的用户数据，跳过处理: {user}")
            continue
        
        # 获取当前用户的更新时间
        current_update_time = user.get("app_account__update_time", "")
        current_timestamp = _parse_update_time(current_update_time)
        
        if user_id in user_dict:
            # 发现重复记录，记录重复信息
            duplicate_count += 1
            existing_user = user_dict[user_id]
            existing_update_time = existing_user.get("app_account__update_time", "")
            existing_timestamp = _parse_update_time(existing_update_time)
            
            # 打印重复用户详情
            duplicate_info = {
                "user_id": user_id,
                "user_name": user.get("app_account__account_name", "未知"),
                "existing_update_time": existing_update_time,
                "current_update_time": current_update_time,
                "existing_data": existing_user,
                "current_data": user
            }
            duplicate_records.append(duplicate_info)
            print(f"发现重复用户【ID: {user_id} | 姓名: {duplicate_info['user_name']}】 | 已存在记录更新时间: {existing_update_time} | 当前记录更新时间: {current_update_time}")
            # 比较更新时间，保留最新的记录
            if current_timestamp > existing_timestamp:
                print(f"  → 当前记录更新时间更新，覆盖原有记录")
                user_dict[user_id] = user
            else:
                print(f"  → 原有记录更新时间更新，保留原有记录")
        else:
            # 无重复，直接添加
            user_dict[user_id] = user
    
    # 输出去重统计
    deduplicated_users = list(user_dict.values())
    print(f"\n去重完成统计：")
    print(f"  - 原始数据条数：{len(all_users)}")
    print(f"  - 重复记录数：{duplicate_count}")
    print(f"  - 去重后数据条数：{len(deduplicated_users)}")
    
    # 打印所有重复记录的汇总
    if duplicate_records:
        print(f"\n===== 重复记录汇总（共{len(duplicate_records)}条） =====")
        for dup in duplicate_records:
            print(dup)
    # ===================== 去重逻辑结束 =====================
    # 打印非重复记录的汇总
    print(f"\n===== 独立汇总（共{len(deduplicated_users)}条） =====")
    def get_org_code(user: dict) -> int:
        """提取用户的org_code用于排序（处理异常情况）"""
        try:
            # 获取第一个组织的org_code，转换为整数
            return int(user.get("orgs", [{}])[0].get("idt_org__org_code", 0))
        except (IndexError, ValueError, TypeError):
            # 无组织信息/转换失败时返回0，排在最后
            return 0
    all_users = sorted(deduplicated_users, key=get_org_code,reverse=True)
    for user in all_users:
        print(f"{user}")
    return all_users

async def generate_encrypted_password(plain_password: str = "ZhongYuan-bisheng.##312"):
    # 1. 调用 get_rsa_publish_key 获取公钥字符串
    pubkey_resp = await get_rsa_publish_key()
    pubkey_str = pubkey_resp.data['public_key']  # 提取公钥字符串
    # 2. 将公钥字符串还原为 RSA 公钥对象（PKCS1 格式）
    pubkey = rsa.PublicKey.load_pkcs1(pubkey_str.encode())
    # 3. 用公钥加密明文密码（PKCS1 填充，与示例格式一致）
    # 加密后得到字节串，需编码为 Base64 字符串（示例中密码的格式）
    encrypted_bytes = rsa.encrypt(plain_password.encode("utf-8"), pubkey)
    encrypted_password = base64.b64encode(encrypted_bytes).decode("utf-8")
    return encrypted_password


# 二.创建用户功能
async def sync_user_data():
    # 1.获取所有用户数据
    all_user_data = get_all_user_data()
    if not all_user_data:
        print("错误：无任何用户数据可处理")
        return
    
    # 2. 从zhongyuan_role表读取已有用户数据
    print("\n开始读取zhongyuan_role表已有用户数据...")
    db_user_data = {}
    try:
        db_records = ZhongYuanRoleDao.get_all_user()
        for record in db_records:
            db_user_data[record.user_id] = {
                "id": record.id,
                "user_id": record.user_id,
                "user_uuid": record.user_uuid,
                "account_no": record.account_no,
                "user_name": record.user_name,
                "status": record.status,
                "org_code": record.org_code,
                "org_name": record.org_name,
                "role_id": record.role_id,
                "group_id": record.group_id,
                "bisheng_user_id": record.bisheng_user_id  # 新增：读取bisheng_user_id
            }
        print(f"成功读取 {len(db_user_data)} 条数据库用户记录")
    except Exception as e:
        print(f"读取zhongyuan_role表失败：{str(e)}")
        return
    
    # 3. 重新获取完整的 org_code 到 group_id 映射（确保最新）
    org_code_group_mapping = get_org_code_to_group_id_mapping()
    if not org_code_group_mapping:
        print("错误：无组织编码-分组ID映射数据，无法创建用户")
        return
    # 4.根据group_id 获取改用户下的角色role_id
    group_id = org_code_group_mapping['gs1']
    print(f"获取到组织编码：gs1,对应的分组ID：{group_id}")
    global_role_id = None
    try:
        resp = await get_group_roles(group_id=[group_id],user=login_user,page=0,limit=0,keyword="组织-角色")
        if resp.status_code == 200:
            global_role_id = resp.data['data'][0].id
            print(f"获取到的全局role_id：{global_role_id}")  # 输出 4203
        else:
            print(f"获取分组ID：{group_id}下的角色ID失败：{resp}")
            return
    except Exception as e:
        print(f"获取分组ID：{group_id}下的角色ID失败：{str(e)}")
        return
    # 5. 循环处理用户数据
    print(f"\n开始处理 {len(all_user_data)} 条用户数据...")
    success_user_create = 0  # 用户创建成功数
    existed_count = 0        # 已存在用户数
    fail_count = 0           # 处理失败数
    fail_users = []          # 失败用户列表
    disable_success_count = 0  # 禁用用户成功数
    enable_success_count = 0   # 启用用户成功数
    status_update_count = 0    # 状态更新成功数
    
    for user in all_user_data:
        # 解析用户原始字段
        user_id = user.get("app_account__id")
        user_account_uuid = user.get("app_account__account_uuid")
        user_account_no = user.get("app_account__account_no")
        user_account_name = user.get("app_account__account_name")
        user_status = user.get("app_account__status", 1)  # 1:启用 0:禁用
        user_update_time = user.get("app_account__update_time")
        request_log_action_desc = user.get("request_log__action_desc", "自动同步用户")
        orgs_list = user.get("orgs", [])
        org_code = ""
        org_name = ""
        sup_org_code = ""
        if orgs_list and len(orgs_list) > 0:
            first_org = orgs_list[0]
            org_code = first_org.get("idt_org__org_code", "")
            org_name = first_org.get("idt_org__name", "")
            sup_org_code = first_org.get("idt_org__sup_org_code", "")
        
        # 基础校验
        if not user_id:
            print(f"跳过：无app_account__id的无效数据 {user}")
            fail_count += 1
            continue
        
        print(f"\n--- 处理用户：{user_account_name}（ID：{user_id}）---")
        
        # 判断用户是否已存在于数据库
        if user_id in db_user_data:
            print(f"用户 {user_id} 已存在于zhongyuan_role表，检查状态是否需要更新")
            db_record = db_user_data[user_id]
            bisheng_user_id = db_record.get("bisheng_user_id")
            
            # 状态不一致则更新
            if user_status != db_record["status"]:
                print(f"用户 {user_id} 状态不一致：数据库{db_record['status']} → 新状态{user_status}")
                if not bisheng_user_id:
                    print(f"警告：用户 {user_id} 无bisheng_user_id，无法更新状态")
                    fail_count += 1
                    fail_users.append(f"{user_account_name}（ID：{user_id}）- 无bisheng_user_id")
                else:
                    try:
                        # status=1 启用（delete=0），status=0 禁用（delete=1）
                        user_update = UserUpdate(
                            user_id=bisheng_user_id,
                            delete=0 if user_status == 1 else 1
                        )
                        update_resp = await update(
                            request=request, 
                            user=user_update, 
                            login_user=login_user
                        )
                        if update_resp.status_code == 200:
                            print(f"✅ 用户 {user_id} 状态更新成功：{'启用' if user_status == 1 else '禁用'}")
                            status_update_count += 1
                            if user_status == 0:
                                disable_success_count += 1
                            else:
                                enable_success_count += 1
                            # 更新数据库中的状态
                            ZhongYuanRoleDao.update_user_status(user_id, user_status)
                        else:
                            print(f"❌ 用户 {user_id} 状态更新失败：响应码 {update_resp.status_code}")
                            fail_count += 1
                            fail_users.append(f"{user_account_name}（ID：{user_id}）- 状态更新失败，响应码{update_resp.status_code}")
                    except Exception as e:
                        error_msg = f"用户 {user_id} 状态更新异常：{str(e)}"
                        print(f"❌ {error_msg}")
                        fail_count += 1
                        fail_users.append(f"{user_account_name}（ID：{user_id}）- {error_msg[:50]}")
            
            existed_count += 1
            continue
        
        # 用户不存在，创建用户（使用全局role_id）
        if not org_code or org_code not in org_code_group_mapping:
            error_msg = f"组织编码 {org_code} 无对应分组ID"
            print(f"❌ 跳过：用户 {user_id} {error_msg}")
            fail_count += 1
            fail_users.append(f"{user_account_name}（ID：{user_id}）- {error_msg}")
            continue
        
        # 获取用户所属组织的分组ID
        user_group_id = org_code_group_mapping[org_code]
        bisheng_user_id = None
        user_create_success = False
        
        try:
            # 创建用户（使用全局角色ID）
            print(f"\n开始创建用户：{user_account_name}")
            user_name = user_account_no
            if global_role_id:
                print(f"\n开始创建主角色对应的用户：{user_name}")
                pub_str = await generate_encrypted_password()
                group_and_roles_1 = GroupAndRoles(group_id=group_id, role_ids=[global_role_id])
                group_and_roles_2 = GroupAndRoles(group_id=user_group_id, role_ids=[])
                req = CreateUserReq(user_name=f"{user_name}", password=pub_str, group_roles=[group_and_roles_1, group_and_roles_2])
                MAX_RETRIES = 3
                user_create_success = False
                created_user = None
                for i in range(MAX_RETRIES):
                    try:
                        created_user = UserService.create_user(request, login_user, req)
                        bisheng_user_id = created_user.user_id  # 新增：获取创建用户的ID
                        print(f"✅ 创建用户成功,用户名为:{created_user.user_name},密码为:{created_user.password},bisheng_user_id:{bisheng_user_id}")
                        user_create_success = True
                        success_user_create += 1
                        break
                    except HTTPException  as e:
                        print(e)
                        if str(e) == "10605: 用户名已存在": 
                            req.user_name = f"{user_name}-{user_id[-6:]}"
                            print(f"❌ 创建用户失败：用户名已存在,重新生成新用户名{req.user_name}")
                        else:
                            print(f"❌ 创建用户失败：{str(e)}")
                            break
                    except Exception as e:
                        print(f"❌ 创建用户失败：{str(e)}")
                        break
                if not user_create_success:
                    raise Exception(f"主角色用户创建失败（重试{MAX_RETRIES}次后仍失败）")
            # 创建成功后处理状态（禁用/启用）
            if user_status == 0 and bisheng_user_id:
                print(f"\n开始禁用用户：{user_account_name}（bisheng_user_id：{bisheng_user_id}）")
                try:
                    user_update = UserUpdate(user_id=bisheng_user_id, delete=1)
                    update_resp = await update(
                        request=request, 
                        user=user_update, 
                        login_user=login_user
                    )
                    if update_resp.status_code == 200:
                        print(f"✅ 禁用用户成功：{user_account_name}")
                        disable_success_count += 1
                    else:
                        print(f"❌ 禁用用户失败：响应码 {update_resp.status_code}")
                except Exception as e:
                    print(f"⚠️ 禁用用户异常（用户已创建）：{str(e)}")
            
            # 写入zhongyuan_role表
            zhongyuan_role_create = ZhongYuanRoleCreate(
                user_id=user_id,
                user_uuid=user_account_uuid,
                account_no=user_account_no,
                user_name=user_account_name,
                status=user_status,
                operation_desc=request_log_action_desc,
                org_name=org_name,
                org_code=org_code,
                sup_org_code=sup_org_code,
                role_id=global_role_id,
                group_id=user_group_id,
                bisheng_user_id=bisheng_user_id
            )
            saved_record = ZhongYuanRoleDao.insert_user(zhongyuan_role_create)
            print(f"✅ 用户 {user_id} 数据已写入zhongyuan_role表（ID：{saved_record.id}）")
            
        except Exception as e:
            error_msg = f"用户 {user_id} 处理失败：{str(e)}"
            print(f"❌ {error_msg}")
            fail_count += 1
            fail_users.append(f"{user_account_name}（ID：{user_id}）- {error_msg[:50]}")
    # 输出统计结果
    print("\n========== 用户处理流程结束 ==========")
    print(f"统计汇总：")
    print(f"   - 新创建用户成功：{success_user_create} 个")
    print(f"   - 成功禁用用户：{disable_success_count} 个")
    print(f"   - 成功启用用户：{enable_success_count} 个")
    print(f"   - 状态更新成功：{status_update_count} 个")
    print(f"   - 已存在用户：{existed_count} 个")
    print(f"   - 处理失败：{fail_count} 个")
    print(f"   - 总计处理用户：{len(all_user_data)} 个")
    if fail_users:
        print(f"   - 失败详情：{', '.join(fail_users[:10])}{'...' if len(fail_users) > 10 else ''}")
async def sync_task():
    """定时执行的同步任务"""
    try:
        generate_new_log_file()
        await sync_group_data() # 1. 同步组织数据
        await sync_user_data()  # 2. 同步用户数据
    except Exception as e:
        print(f"定时任务执行异常：{str(e)}")

def parse_cli_args():
    """解析命令行参数，获取目标执行小时"""
    # 1. 检查参数数量：必须传1个参数（如 python main.py 2）
    if len(sys.argv) != 2:
        print("用法错误！正确用法：python main.py <小时数>")
        print("示例：python main.py 2 （每天凌晨2点执行）")
        sys.exit(1)  # 非0退出码表示执行失败
    
    # 2. 解析并校验参数（必须是0-23的整数）
    try:
        target_hour = int(sys.argv[1])
        if not 0 <= target_hour <= 23:
            raise ValueError("小时数必须在0-23之间")
        return target_hour
    except ValueError as e:
        print(f"参数错误：{e}")
        print("请传入0-23之间的整数（如 2 表示凌晨2点，18 表示下午6点）")
        sys.exit(1)

async def scheduled_task(target_hour: int):
    """每天指定小时执行任务（分钟固定为0）"""
    target_minute = 0  # 固定凌晨X点整执行，也可改为传参（见扩展）
    while True:
        try:
            # 执行核心任务
            await sync_task()
            # 计算下一次执行时间
            now = datetime.datetime.now()
            next_run = now.replace(
                hour=target_hour,
                minute=target_minute,
                second=0,
                microsecond=0
            )
            # 若当前时间已过今日目标时间，顺延至次日
            if now >= next_run:
                next_run += datetime.timedelta(days=1)
            # 计算等待时长
            wait_seconds = (next_run - now).total_seconds()
            wait_hours = wait_seconds / 3600
            next_run_str = next_run.strftime("%Y-%m-%d %H:%M:%S")
            # 打印调度信息
            print(f"\n下一次任务将在 {next_run_str} 执行（等待约 {wait_hours:.1f} 小时）")
            await asyncio.sleep(wait_seconds)
        except Exception as e:
            print(f"任务执行出错: {str(e)}，1分钟后重新计算调度时间")
            await asyncio.sleep(60)  # 出错后避免频繁重试

if __name__ == "__main__":
    # 解析命令行参数
    target_hour = parse_cli_args()
    print(f"定时任务已启动，每天凌晨 {target_hour} 点执行...")
    # 启动定时任务
    asyncio.run(scheduled_task(target_hour))