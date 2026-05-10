import asyncio
import os
import sys

# Ensure the parent directory is in path so we can import bisheng modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bisheng.knowledge.domain.models.knowledge import KnowledgeDao
from bisheng.user.domain.models.user import User
from bisheng.core.database import get_sync_db_session

def test_auth():
    print("========== 毕昇多级权限引擎测试 ==========")
    
    # 假设测试用户的 explicit_ids 是 [1] (代表拥有 kb1 的权限)
    test_explicit_ids = [1]
    
    print(f"\\n[1] 开始模拟计算用户的领土地图...")
    print(f"输入: 用户的原始授权节点 = {test_explicit_ids}")
    
    try:
        # 1. 测试穿透算法
        granted_map = KnowledgeDao.get_granted_kbs_and_descendants(test_explicit_ids)
        print(f"\\n✅ 广度优先(BFS)穿透结果:")
        print(f"计算出的领土地图: {granted_map}")
        if 2 in granted_map and 3 in granted_map:
            print("🎉 成功: kb2 和 kb3 已被自动穿透并包含在权限范围内！")
        else:
            print("❌ 失败: kb2 和 kb3 没有被包含进去。")
            
        # 2. 测试权限拦截器
        print(f"\\n[2] 开始模拟 RAG 拦截器调用 judge_knowledge_permission()...")
        
        # 为了测试，我们在数据库里直接找 user_id = 2 的真实 user_name
        with get_sync_db_session() as session:
            test_user = session.get(User, 2)
            if not test_user:
                print("❌ 无法在数据库中找到 user_id = 2 的测试账号，请确认该账号存在！")
                return
            test_user_name = test_user.user_name
        
        print(f"找到测试账号: {test_user_name}")
        
        # 模拟访问 kb1
        print(f"\\n尝试访问 kb1 (总局)...")
        result_1 = KnowledgeDao.judge_knowledge_permission(test_user_name, [1])
        print(f"权限结果: {'✅ 允许' if result_1 else '❌ 拦截'}")
        
        # 模拟访问 kb2
        print(f"\\n尝试访问 kb2 (分局，用户没有直接挂载，需靠穿透)...")
        result_2 = KnowledgeDao.judge_knowledge_permission(test_user_name, [2])
        print(f"权限结果: {'✅ 允许' if result_2 else '❌ 拦截'}")
        
        # 模拟越权访问
        print(f"\\n尝试访问 kb999 (不存在或无权限的孤岛节点)...")
        result_999 = KnowledgeDao.judge_knowledge_permission(test_user_name, [999])
        print(f"权限结果: {'✅ 允许' if result_999 else '❌ 拦截'}")
        
    except Exception as e:
        print(f"\\n❌ 测试过程中发生错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_auth()
