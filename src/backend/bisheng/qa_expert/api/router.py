"""
Expert QA Router - 路由注册

在 api/router.py 中通过以下方式注册：
from bisheng.qa_expert.api.router import router as qa_router
router.include_router(qa_router)
"""

from fastapi import APIRouter
from bisheng.qa_expert.api import endpoints

# 创建路由
router = APIRouter(prefix="/qa_experts", tags=["Expert QA"])

# 注册端点
# 专家管理
router.add_api_route("/experts", endpoints.list_experts, methods=["GET"])


# 问题管理
router.add_api_route("/questions", endpoints.create_question, methods=["POST"])
router.add_api_route("/questions", endpoints.list_questions, methods=["GET"])
router.add_api_route("/questions/{question_id}", endpoints.get_question_detail, methods=["GET"])
router.add_api_route("/questions/{question_id}/adopt", endpoints.adopt_answer, methods=["POST"])

# 回答管理
router.add_api_route("/answers", endpoints.create_answer, methods=["POST"])
router.add_api_route("/answers/{question_id}", endpoints.get_answers, methods=["GET"])
router.add_api_route("/answers/{answer_id}", endpoints.update_answer, methods=["PUT"])
router.add_api_route("/answers/{answer_id}", endpoints.delete_answer, methods=["DELETE"])

# 评论管理
router.add_api_route("/comments", endpoints.create_comment, methods=["POST"])
router.add_api_route("/comments/{answer_id}", endpoints.get_comments, methods=["GET"])

# 投票
router.add_api_route("/votes/question", endpoints.vote_question, methods=["POST"])
router.add_api_route("/votes/answer", endpoints.vote_answer, methods=["POST"])

# 通知
router.add_api_route("/notifications", endpoints.get_notifications, methods=["GET"])
router.add_api_route("/notifications/{notification_id}/read", endpoints.mark_notification_read, methods=["POST"])

# 草稿
router.add_api_route("/drafts", endpoints.save_draft, methods=["POST"])
router.add_api_route("/drafts", endpoints.get_draft, methods=["GET"])
router.add_api_route("/drafts", endpoints.delete_draft, methods=["DELETE"])
