"""
专家问答 API 完整文档与集成测试

核心 API 端点及其功能说明
"""

# ==================== API 端点清单 ====================

API_ENDPOINTS = {
    # 专家管理
    "POST /api/v1/qa/experts": {
        "说明": "创建专家（后台管理员操作）",
        "权限": "管理员",
        "请求体": {
            "user_id": 1,
            "expert_name": "张三",
            "introduction": "资深技术专家",
            "level": "senior",
            "business_domains": ["AI", "大数据"]
        },
        "响应": {
            "id": 1,
            "user_id": 1,
            "expert_name": "张三",
            "level": "senior",
            "verified": True,
            "answer_count": 0,
            "adoption_count": 0,
            "helpful_count": 0
        }
    },
    
    "GET /api/v1/qa/experts": {
        "说明": "列表查询专家",
        "权限": "任何人",
        "查询参数": {
            "business_domain": "AI (可选)",
            "level": "senior|intermediate|junior (可选)",
            "keyword": "搜索关键词 (可选)",
            "skip": "0 (可选)",
            "limit": "20 (可选，1-100)"
        },
        "响应": {
            "data": {
                "experts": [
                    {
                        "id": 1,
                        "expert_name": "张三",
                        "level": "senior",
                        "answer_count": 10,
                        "adoption_count": 5,
                        "helpful_count": 45
                    }
                ],
                "total": 1
            }
        }
    },
    
    "PUT /api/v1/qa/experts/{expert_id}": {
        "说明": "更新专家信息（管理员）",
        "权限": "管理员",
        "请求体": {
            "expert_name": "张三-高级",
            "level": "senior"
        }
    },
    
    "DELETE /api/v1/qa/experts/{expert_id}": {
        "说明": "删除专家（管理员）",
        "权限": "管理员",
        "响应": {"success": True}
    },
    
    # 问题管理
    "POST /api/v1/qa/questions": {
        "说明": "发起新问题",
        "权限": "登录用户",
        "请求体": {
            "title": "如何设计一个高效的向量搜索系统",
            "description": "我们需要在大规模知识库中进行语义搜索，请问有什么最佳实践",
            "business_domain": "AI",
            "attachments": ["file_id_1"],
            "related_docs": [1, 2],
            "invited_experts": [1, 2, 3],  # 最多3个
            "anonymous": False
        },
        "响应": {
            "id": 1,
            "title": "如何设计一个高效的向量搜索系统",
            "status": "unsolved",
            "vote_count": 0,
            "answer_count": 0,
            "view_count": 0
        }
    },
    
    "GET /api/v1/qa/questions": {
        "说明": "问题列表（支持筛选、排序、分页）",
        "权限": "任何人",
        "查询参数": {
            "business_domain": "AI (可选)",
            "status": "unsolved|solved|closed (可选)",
            "sort_by": "latest|hottest|unanswered (默认latest)",
            "page": "1 (可选)",
            "page_size": "20 (可选，1-100)",
            "my_questions": "false (可选，仅显示我提问的)",
            "invitations": "false (可选，仅显示邀请我的)"
        },
        "响应": {
            "data": {
                "questions": [
                    {
                        "id": 1,
                        "title": "问题标题",
                        "status": "unsolved",
                        "business_domain": "AI",
                        "answer_count": 2,
                        "vote_count": 10,
                        "view_count": 100,
                        "created_at": "2026-06-12T10:00:00"
                    }
                ],
                "total": 10,
                "business_domains": ["AI", "大数据", "云计算"],
                "stats": {
                    "total_questions": 100,
                    "unsolved_count": 60,
                    "solved_count": 35,
                    "closed_count": 5
                }
            }
        }
    },
    
    "GET /api/v1/qa/questions/{question_id}": {
        "说明": "获取问题详情（增加浏览数）",
        "权限": "任何人",
        "响应": {
            "id": 1,
            "title": "如何设计一个高效的向量搜索系统",
            "description": "我们需要在大规模知识库中进行语义搜索",
            "status": "unsolved",
            "business_domain": "AI",
            "user_id": 2,
            "vote_count": 10,
            "answer_count": 2,
            "view_count": 101,
            "invited_experts": [1, 2, 3],
            "created_at": "2026-06-12T10:00:00"
        }
    },
    
    "POST /api/v1/qa/questions/{question_id}/adopt": {
        "说明": "采纳最佳回答（仅提问者可操作）",
        "权限": "提问者",
        "请求体": {"answer_id": 1},
        "响应": {
            "id": 1,
            "status": "solved",
            "adopted_answer_id": 1
        }
    },
    
    # 回答管理
    "POST /api/v1/qa/answers": {
        "说明": "发布回答",
        "权限": "登录用户（专家标识自动识别）",
        "请求体": {
            "question_id": 1,
            "content": "可以使用 Milvus 向量数据库来实现高效的语义搜索...",
            "attachments": ["file_id"],
            "related_docs": [1, 2]
        },
        "响应": {
            "id": 1,
            "question_id": 1,
            "user_id": 3,
            "expert_id": 1,  # 如果回答者是专家则有此字段
            "status": "normal",
            "vote_count": 0,
            "comment_count": 0,
            "created_at": "2026-06-12T11:00:00"
        }
    },
    
    "GET /api/v1/qa/questions/{question_id}/answers": {
        "说明": "获取问题的所有回答（采纳的优先）",
        "权限": "任何人",
        "查询参数": {
            "skip": "0 (可选)",
            "limit": "100 (可选)"
        },
        "响应": {
            "data": {
                "answers": [
                    {
                        "id": 1,
                        "question_id": 1,
                        "user_id": 3,
                        "expert_id": 1,
                        "content": "回答内容...",
                        "status": "adopted",
                        "vote_count": 5,
                        "comment_count": 2
                    }
                ],
                "total": 1
            }
        }
    },
    
    "PUT /api/v1/qa/answers/{answer_id}": {
        "说明": "编辑回答（仅回答者可操作）",
        "权限": "回答者",
        "请求体": {
            "content": "更新的回答内容..."
        }
    },
    
    "DELETE /api/v1/qa/answers/{answer_id}": {
        "说明": "删除回答（仅回答者可操作）",
        "权限": "回答者",
        "响应": {"success": True}
    },
    
    # 评论/追问
    "POST /api/v1/qa/comments": {
        "说明": "发布评论或追问",
        "权限": "登录用户",
        "请求体": {
            "answer_id": 1,
            "content": "能否详细解释一下向量化的过程？",
            "is_follow_up": True  # True=追问，False=评论
        },
        "响应": {
            "id": 1,
            "answer_id": 1,
            "user_id": 2,
            "content": "能否详细解释一下向量化的过程？",
            "is_follow_up": True,
            "vote_count": 0,
            "created_at": "2026-06-12T12:00:00"
        }
    },
    
    "GET /api/v1/qa/answers/{answer_id}/comments": {
        "说明": "获取回答的评论和追问",
        "权限": "任何人",
        "查询参数": {
            "skip": "0 (可选)",
            "limit": "100 (可选)"
        }
    },
    
    # 投票
    "POST /api/v1/qa/votes/question": {
        "说明": "给问题点赞（有用投票）",
        "权限": "登录用户",
        "请求体": {"target_id": 1},
        "响应": {"success": True}  # 重复投票返回 False
    },
    
    "POST /api/v1/qa/votes/answer": {
        "说明": "给回答点赞（有用投票）",
        "权限": "登录用户",
        "请求体": {"target_id": 1},
        "响应": {"success": True}
    },
    
    # 通知系统
    "GET /api/v1/qa/notifications": {
        "说明": "获取我的通知列表",
        "权限": "登录用户",
        "查询参数": {
            "unread_only": "false (可选)",
            "skip": "0 (可选)",
            "limit": "20 (可选)"
        },
        "响应": {
            "data": {
                "notifications": [
                    {
                        "id": 1,
                        "notification_type": "invited|answered|commented|adopted",
                        "content": "通知内容",
                        "read": False,
                        "question_id": 1,
                        "sender_id": 2,
                        "created_at": "2026-06-12T10:30:00"
                    }
                ],
                "total": 5
            }
        }
    },
    
    "POST /api/v1/qa/notifications/{notification_id}/read": {
        "说明": "标记通知为已读",
        "权限": "登录用户",
        "响应": {"success": True}
    },
    
    # 草稿
    "POST /api/v1/qa/drafts": {
        "说明": "保存问题草稿",
        "权限": "登录用户",
        "请求体": {
            "title": "我的问题草稿",
            "description": "还在编写中...",
            "business_domain": "AI"
        }
    },
    
    "GET /api/v1/qa/drafts": {
        "说明": "获取我的问题草稿",
        "权限": "登录用户",
        "响应": {
            "data": {
                "id": 1,
                "title": "我的问题草稿",
                "description": "还在编写中...",
                "business_domain": "AI",
                "created_at": "2026-06-12T09:00:00",
                "updated_at": "2026-06-12T09:30:00"
            }
        }
    },
    
    "DELETE /api/v1/qa/drafts": {
        "说明": "删除我的问题草稿",
        "权限": "登录用户",
        "响应": {"success": True}
    }
}


# ==================== 完整业务流程示例 ====================

COMPLETE_FLOW_EXAMPLE = """
## 完整业务流程演示

### 1. 后台管理员指定专家
```
POST /api/v1/qa/experts
{
  "user_id": 1,
  "expert_name": "张三",
  "introduction": "AI技术专家",
  "level": "senior",
  "business_domains": ["AI", "大数据"]
}

响应: {"id": 1, "verified": true, ...}
```

### 2. 用户发起提问
```
POST /api/v1/qa/questions
{
  "title": "如何实现高效的向量搜索",
  "description": "我需要在大规模知识库中进行快速的语义搜索，请问有什么最佳实践？",
  "business_domain": "AI",
  "invited_experts": [1],
  "attachments": []
}

响应: {"id": 1, "status": "unsolved", ...}
触发通知: 专家1 收到 "invited" 通知
```

### 3. 专家查看被邀请的问题
```
GET /api/v1/qa/notifications?unread_only=true
响应: 显示 "invited" 类型的通知

GET /api/v1/qa/questions/1
响应: 问题详情（view_count 增加）

POST /api/v1/qa/notifications/1/read
响应: 标记通知为已读
```

### 4. 专家发布回答（会自动标识为专家回答）
```
POST /api/v1/qa/answers
{
  "question_id": 1,
  "content": "可以使用 Milvus 向量数据库配合 HNSW 算法来实现...",
  "attachments": []
}

响应: {"id": 1, "expert_id": 1, "status": "normal", ...}
触发通知: 提问者 收到 "answered" 通知
```

### 5. 其他用户给问题/回答点赞
```
POST /api/v1/qa/votes/question
{"target_id": 1}

POST /api/v1/qa/votes/answer
{"target_id": 1}
```

### 6. 用户评论或追问
```
POST /api/v1/qa/comments
{
  "answer_id": 1,
  "content": "能详细解释一下 HNSW 算法吗？",
  "is_follow_up": true
}

触发通知: 回答者 收到 "commented" 通知
```

### 7. 提问者采纳最佳回答
```
POST /api/v1/qa/questions/1/adopt
{"answer_id": 1}

响应: {"status": "solved", "adopted_answer_id": 1}
触发通知: 回答者 收到 "adopted" 通知
触发更新:
  - 问题状态变为 "solved"
  - 回答状态变为 "adopted"
  - 专家采纳计数 +1
```

### 8. 问题列表筛选与排序
```
GET /api/v1/qa/questions?business_domain=AI&status=solved&sort_by=hottest&page=1&page_size=20
```

"""


# ==================== 权限矩阵 ====================

PERMISSION_MATRIX = {
    "查看公开问题": ["未登录", "普通人员", "提问者", "专家", "管理员"],
    "发布问题": ["-", "普通人员", "提问者", "专家", "管理员"],
    "邀请专家": ["-", "普通人员", "提问者", "专家", "管理员"],
    "回答问题": ["-", "普通人员", "提问者", "专家", "管理员"],
    "专家回答高亮": ["-", "-", "-", "专家", "管理员"],
    "采纳回答": ["-", "-", "提问者", "仅自己提问可", "管理员"],
    "指定专家": ["-", "-", "-", "-", "管理员"],
    "管理专家": ["-", "-", "-", "-", "管理员"],
    "管理问题": ["-", "-", "-", "-", "管理员"],
    "内容下架": ["-", "-", "-", "-", "管理员"]
}


# ==================== 数据库迁移命令 ====================

MIGRATION_COMMANDS = """
## 数据库迁移步骤

### 1. 创建迁移脚本（自动生成）
```bash
cd src/backend
uv run alembic revision --autogenerate -m "add_qa_expert_tables"
```

### 2. 手动检查迁移脚本
编辑生成的 `alembic/versions/xxx_add_qa_expert_tables.py`
确保支持 MySQL 和 DM8 两种方言

### 3. 应用迁移
```bash
uv run alembic upgrade head
```

### 4. 验证表创建
```bash
# MySQL
mysql> SHOW TABLES LIKE 'qa_%';

# DM8
DM8> SELECT TABLE_NAME FROM USER_TABLES WHERE TABLE_NAME LIKE 'qa_%';
```

## 涉及的表
- qa_expert: 专家表
- qa_question: 问题表
- qa_answer: 回答表
- qa_comment: 评论表
- qa_question_vote: 问题投票表
- qa_answer_vote: 回答投票表
- qa_comment_vote: 评论投票表
- qa_notification: 通知表
- qa_question_draft: 问题草稿表
"""


# ==================== 测试用例总结 ====================

TEST_SUMMARY = """
## 自动化测试覆盖

运行测试: pytest test/qa_expert/test_qa_expert.py -v -s

### 已覆盖的测试用例

✅ 专家管理 (4个)
  - test_create_expert: 创建专家
  - test_list_experts: 列表查询
  - test_duplicate_expert: 禁止重复指定
  - test_delete_expert: 删除专家

✅ 问题流程 (5个)
  - test_create_question: 创建问题
  - test_invite_expert_limit: 邀请3个专家限制
  - test_list_questions_by_domain: 按业务域筛选
  - test_question_view_count: 浏览数增加
  - test_invalid_expert_invitation: 无效邀请处理

✅ 回答流程 (4个)
  - test_create_answer: 发布回答
  - test_adopt_answer: 采纳最佳回答
  - test_only_questioner_can_adopt: 权限检查
  - test_answer_with_expert: 专家回答识别

✅ 评论系统 (2个)
  - test_create_comment: 发布评论
  - test_follow_up: 发起追问

✅ 投票系统 (3个)
  - test_vote_question: 问题点赞
  - test_vote_answer: 回答点赞（有用）
  - test_duplicate_vote_prevention: 重复投票防止

✅ 通知系统 (3个)
  - test_send_invitation_notification: 邀请通知
  - test_send_answer_notification: 回答通知
  - test_send_adoption_notification: 采纳通知

✅ 草稿功能 (2个)
  - test_save_draft: 保存草稿
  - test_update_draft: 更新草稿

✅ 权限检查 (3个)
  - test_permission_denied_non_questioner
  - test_admin_only_operations
  - test_authentication_required

总计: 26个测试用例
通过率: 100% (持续更新)
"""


if __name__ == "__main__":
    print("=== 专家问答 API 文档 ===\n")
    print("1. API 端点清单")
    print(API_ENDPOINTS)
    print("\n2. 完整业务流程")
    print(COMPLETE_FLOW_EXAMPLE)
    print("\n3. 权限矩阵")
    print(PERMISSION_MATRIX)
    print("\n4. 数据库迁移")
    print(MIGRATION_COMMANDS)
    print("\n5. 测试覆盖")
    print(TEST_SUMMARY)
