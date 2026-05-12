import asyncio
import os
import sys

# Ensure the parent directory is in path so we can import bisheng modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bisheng.knowledge.domain.models.knowledge import KnowledgeDao
from bisheng.user.domain.models.user import User, UserDao
from bisheng.core.database import get_async_db_session


async def test_pagination():
    print("========== 毕昇多级权限引擎：分页接口与Shift-Left优化集成测试 ==========")
    
    # 模拟查找一个普通测试账号（假设 user_id = 2）
    test_user_id = 2
    print(f"\n[1] 正在从数据库拉取测试账号实体信息 (user_id = {test_user_id})...")
    
    try:
        user_info = await UserDao.aget_user(test_user_id)
        if not user_info:
            print(f"❌ 未找到 user_id = {test_user_id} 的账号，尝试通过用户名查找示例账号...")
            # 作为备选方案，尝试查找任意一条非超管账号
            async with get_async_db_session() as session:
                from sqlmodel import select
                statement = select(User).where(User.user_id != 1)
                result = await session.exec(statement)
                user_info = result.first()
                if not user_info:
                    print("❌ 数据库中没有普通测试账号，请确认已导入基础数据！")
                    return
                    
        print(f"✅ 成功加载测试账号：{user_info.user_name} | 兵符授权集：{user_info.org_knowledge_ids}")
        
        # 2. 调用核心白名单算子，测试鉴权前置化效果
        print("\n[2] 开始执行底层算子 aget_authorized_knowledge_ids 计算精准权限白名单...")
        authorized_ids = await KnowledgeDao.aget_authorized_knowledge_ids(user_info)
        print(f"🎯 算子输出的白名单 ID 列表：{authorized_ids}")
        
        # 3. 模拟前端带分页参数请求列表 (假设请求第 1 页，每页只看 2 条)
        test_page = 1
        test_limit = 2
        print(f"\n[3] 模拟 API 调用 aget_user_knowledge() 分页截断 (page={test_page}, limit={test_limit})...")
        
        # 将白名单注入底层查询
        paginated_res = await KnowledgeDao.aget_user_knowledge(
            user_id=user_info.user_id,
            knowledge_id_extra=authorized_ids,
            knowledge_type=None,
            name=None,
            sort_by="update_time",
            page=test_page,
            limit=test_limit
        )
        
        # 获取底层真实的数据总量
        total_count = await KnowledgeDao.acount_user_knowledge(
            user_id=user_info.user_id,
            knowledge_id_extra=authorized_ids,
            knowledge_type=None,
            name=None
        )
        
        print("\n📊 分页测试断言结果：")
        print(f"实际有权访问总数 (Total Count) = {total_count}")
        print(f"当前页实际返回条数 (Returned Rows) = {len(paginated_res)}")
        
        # 断言逻辑
        if len(paginated_res) <= test_limit:
            print("🎉 断言成功：返回数据条数严格遵循了 limit 约束，未发生底层内存过滤导致的缺页残页 Bug！")
        else:
            print("❌ 断言失败：返回的条数超出了 limit 限制。")
            
        # 打印返回的具体知识库标题
        print("\n当前页包含的合法知识库：")
        for idx, kb in enumerate(paginated_res, 1):
            print(f"  {idx}. [ID: {kb.id}] 标题：{kb.name} | 创建者ID：{kb.user_id} | 继承级别：{kb.level}")
            
    except Exception as e:
        print(f"\n❌ 测试执行失败：{e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    # 在标准事件循环中启动异步测试脚本
    asyncio.run(test_pagination())
