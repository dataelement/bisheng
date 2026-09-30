"""统计任务状态检查及显式重放; 默认只读, 不清空队列。"""

import argparse
import importlib
import json

from bisheng.core.cache.redis_manager import get_redis_client_sync
from bisheng.telemetry.domain.mid_table.knowledge_space_content import KnowledgeSpaceContentStat
from bisheng.telemetry.domain.mid_table.retry_budget import TASK_MODULES, RunBudget


def dispatch(name, invocation=None):
    task = getattr(importlib.import_module(TASK_MODULES[name]), name)
    saved = json.loads(invocation or "{}")
    task.apply_async(args=saved.get("args", []), kwargs=saved.get("kwargs", {}))


def execute(args):
    if args.job:
        budget = RunBudget(args.job)
        before = budget.status()
        result = {"job": args.job, "before": before, "apply": args.apply}
        if args.apply:
            if not budget.reset():
                raise RuntimeError("任务仍在执行, 不能重置预算")
            dispatch(args.job, before.get("invocation"))
            result["after"] = budget.status()
        return result
    cls = KnowledgeSpaceContentStat
    events = args.queue == "events"
    key = cls.EVENT_DEAD_KEY if events else cls.DEAD_KEY
    redis = get_redis_client_sync()
    redis.cluster_nodes(key)
    connection = redis.connection
    if not args.member:
        cursor, entries = connection.hscan(key, cursor=args.cursor, count=1000)
        return {
            "queue": args.queue,
            "dead_count": connection.hlen(key),
            "cursor": cursor,
            "entries": {cls._decode_text(k): cls._decode_text(v) for k, v in entries.items()},
        }
    before = cls._decode_text(connection.hget(key, args.member))
    result = {"queue": args.queue, "member": args.member, "before": before, "apply": args.apply}
    if args.apply:
        if not cls.replay_dead_sync(args.member, events=events):
            raise RuntimeError("记录不存在于终止队列或仍在处理中, 未重放")
        name = "sync_pending_knowledge_space_content_events" if events else "sync_pending_knowledge_space_content_stat"
        dispatch(name)
        result["job_state"] = RunBudget(name).status()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--job", choices=sorted(TASK_MODULES))
    target.add_argument("--queue", choices=("files", "events"))
    parser.add_argument("--member")
    parser.add_argument("--cursor", type=int, default=0)
    parser.add_argument("--apply", action="store_true", help="重置指定任务预算或重放指定终止记录, 并调度处理")
    args = parser.parse_args()
    if args.apply and args.queue and not args.member:
        parser.error("--apply 必须指定一个 --member, 禁止批量清空失败状态")
    if args.member and not args.queue:
        parser.error("--member 只能与 --queue 一起使用")
    print(json.dumps(execute(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
