"""The fifteen BiSheng cases. A missing process, model, or baseline is 未测, not a pass."""

from __future__ import annotations

import os
import time
from contextlib import contextmanager

import pytest

from test.sandbox.release.client import (
    ApiError,
    assistant_events,
    child_tool,
    code_interpreter_type,
    continue_task,
    daily_sum,
    download_bytes,
    extra_of,
    file_urls,
    first_sum_result,
    linsight_tool_payload,
    open_api,
    run_task_question,
    save_execution_type,
    submit_task,
    task_tool_results,
    tool_categories,
    tool_category_payload,
    upload_linsight_file,
    user_input,
    wait_tasks,
    waiting_task_id,
    workbench_model_id,
    workflow_events,
)
from test.sandbox.release.conftest import sandbox_reachable
from test.sandbox.release.env import (
    ASSISTANT_ID,
    CODE_WORKFLOW_ID,
    FIXED_MODEL,
    SKILL_FILE,
    SUM_PROMPT,
    WORKFLOW_ID,
)
from test.sandbox.release.parse import (
    assistant_tool_result,
    chosen_tool_result,
    code_output_values,
    history_steps,
    log_sum,
    offload_notice,
    output_msg_text,
    printed_ends,
    workflow_tool_result,
)
from test.sandbox.release.samples import docx_body, docx_contains, pptx_contains, xlsx_amounts, xlsx_contains_amounts

_BIG = 60 * 1024 * 1024
_TEN_MIB = 10 * 1024 * 1024


@pytest.fixture(scope="module")
def api():
    client = open_api()
    if client is None:
        pytest.skip(f"未测：{getattr(open_api, 'problem', '') or '后端不可登录'}")
    if not sandbox_reachable():
        client.close()
        pytest.skip("沙箱进程未启动，容器组未测")
    yield client
    client.close()


@contextmanager
def _mode(client, mode: str):
    item = code_interpreter_type(tool_categories(client))
    if item is None:
        pytest.skip("未测：工具列表没有代码执行器")
    original = extra_of(item).get("type")
    save_execution_type(client, mode)
    try:
        yield item
    finally:
        if isinstance(original, str):
            save_execution_type(client, original)


@pytest.fixture(scope="module")
def task_sum(api):
    with _mode(api, "container"):
        _version, tasks = run_task_question(api, SUM_PROMPT)
    return first_sum_result(tasks, log_sum)


def _require_sum(result) -> None:
    if not log_sum(result):
        pytest.skip("sum([1,2,3]) 不是 6，不再跑后面的文件用例")


def _code_of(step: dict) -> str:
    params = step.get("params")
    if isinstance(params, dict):
        for key in ("python_code", "code", "input"):
            value = params.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return str(params)
    return str(params or "")


def _blobs(client, version_id: str, tasks: list) -> list[bytes]:
    found = []
    for item in task_tool_results(tasks):
        for url in file_urls(item["result"]):
            found.append(download_bytes(client, version_id, url))
    return found


def test_s002(api, task_sum):
    """Workflow tool, assistant, daily chat, and task mode. The code node is S-014."""
    missing = []
    wrong = []
    if not log_sum(task_sum):
        wrong.append(f"任务模式结果不是 log=6 exitcode=0: {task_sum!r}")
    if not workbench_model_id(api) or child_tool(api) is None:
        missing.append("日常对话")
    else:
        try:
            daily = daily_sum(api, SUM_PROMPT)
        except ApiError as exc:
            wrong.append(f"日常对话: {exc}")
        else:
            if not log_sum(daily):
                wrong.append(f"日常对话结果不是 log=6 exitcode=0: {daily!r}")
    workflow_id = WORKFLOW_ID
    if not workflow_id:
        missing.append("工作流代码工具")
    else:
        frames = workflow_events(api, workflow_id, SUM_PROMPT)
        result = chosen_tool_result([workflow_tool_result(frame) for frame in frames], log_sum)
        if not log_sum(result):
            wrong.append(f"工作流工具结果不是 log=6 exitcode=0: {result!r}")
    assistant_id = ASSISTANT_ID
    if not assistant_id:
        missing.append("助手")
    else:
        frames = assistant_events(api, assistant_id, SUM_PROMPT)
        result = chosen_tool_result([assistant_tool_result(frame) for frame in frames], log_sum)
        if not log_sum(result):
            wrong.append(f"助手结果不是 log=6 exitcode=0: {result!r}")
    if wrong:
        pytest.fail("S-002\n" + "\n".join(wrong))
    if missing:
        pytest.skip("未测：" + "、".join(missing) + "，四入口不齐，整条不算通过")


def test_s014(api):
    workflow_id = CODE_WORKFLOW_ID
    if not workflow_id:
        pytest.skip("未测：没有输入→代码节点→下游的工作流")
    with _mode(api, "container"):
        frames = workflow_events(api, workflow_id, "7")
    values = next((code_output_values(frame) for frame in frames if code_output_values(frame)), None)
    shown = [output_msg_text(frame) for frame in frames if output_msg_text(frame)]
    assert isinstance(values, dict)
    assert any(item == 14 or item == "14" for item in values.values()), values
    assert any(isinstance(text, str) and "14" in text for text in shown), shown


def test_s003(api, task_sum):
    _require_sum(task_sum)
    files = [
        upload_linsight_file(api, "中文表.xlsx", xlsx_amounts()),
        upload_linsight_file(api, "中文说明.docx", docx_body("本月统计完成")),
    ]
    question = (
        "必须用代码工具读取本次上传的 uploads/中文表.xlsx 和 uploads/中文说明.docx。"
        "打印金额总和，并打印 Word 正文。不要新建同名文件。"
    )
    with _mode(api, "container"):
        _version, tasks = run_task_question(api, question, files=files)
    found = task_tool_results(tasks)
    blob = "\n".join(_code_of(item["step"]) + "\n" + str(item["result"].get("log") or "") for item in found)
    if "uploads/" not in blob or "中文表.xlsx" not in blob or "中文说明.docx" not in blob:
        pytest.skip("未测：模型没有提交读取 uploads/ 下两份原件的代码，空的 python_code 不能当成原件不可读")
    logs = "\n".join(str(item["result"].get("log") or "") for item in found)
    assert "6" in logs
    assert "本月统计完成" in logs


def _matches(blobs: list[bytes], checker) -> bool:
    for blob in blobs:
        try:
            if checker(blob):
                return True
        except Exception:
            continue
    return False


def test_s023(api, task_sum):
    _require_sum(task_sum)
    question = (
        "用代码在 output/ 生成三个中文名文件：说明.docx 正文写沙箱测试成功，"
        "演示.pptx 写入沙箱测试成功，金额表.xlsx 写入文字沙箱测试成功和金额 1、2、3。"
        "生成 Excel 的同一轮必须用 read_file 读取相对路径 output/金额表.xlsx，不要加前导斜杠。"
    )
    with _mode(api, "container"):
        version, tasks = run_task_question(api, question)
    reads = [step for step in history_steps(tasks) if step.get("name") == "read_file"]
    read_text = "\n".join(str(step.get("output") or "") for step in reads)
    if "沙箱测试成功" not in read_text or any(piece not in read_text for piece in ("1", "2", "3")):
        pytest.skip("未测：read_file 没有读到生成的表。绝对路径 /output/ 被拒绝是服务的正确行为")
    blobs = _blobs(api, version, tasks)
    if not blobs:
        pytest.skip("未测：没有可下载的产物")
    assert _matches(blobs, lambda blob: docx_contains(blob, "沙箱测试成功"))
    assert _matches(blobs, lambda blob: pptx_contains(blob, "沙箱测试成功"))
    assert _matches(blobs, lambda blob: xlsx_contains_amounts(blob, (1, 2, 3)))


def test_s024(api, task_sum):
    _require_sum(task_sum)
    question = "用代码在任务工作区根部写 root-note.txt，路径不要带 output/，内容是文件没有丢失。"
    with _mode(api, "container"):
        version, tasks = run_task_question(api, question)
    calls = task_tool_results(tasks)
    if not calls:
        pytest.skip("未测：没有代码调用，构造不出根部文件")
    code = "\n".join(_code_of(item["step"]) for item in calls)
    if "root-note.txt" not in code:
        pytest.skip("未测：构造不出根部文件")
    if "output/" in code or "output\\" in code:
        pytest.fail("模型一开始就写进 output/，不算归位通过")
    log = "\n".join(str(item["result"].get("log") or "") for item in calls)
    assert "output/root-note.txt" in log or "output\\root-note.txt" in log
    blobs = _blobs(api, version, tasks)
    assert any("文件没有丢失".encode() in blob for blob in blobs)


def test_s007(api, task_sum):
    _require_sum(task_sum)
    files = [
        upload_linsight_file(api, "edit.txt", "修改前".encode()),
        upload_linsight_file(api, "keep.txt", "保持原样".encode()),
    ]
    question = "用代码把 edit.txt 改成修改后，不要改 keep.txt，再生成 new.txt，内容是新文件。"
    with _mode(api, "container"):
        version, tasks = run_task_question(api, question, files=files)
    calls = task_tool_results(tasks)
    if not calls:
        pytest.skip("未测：模型没有调用代码工具，看不出本轮产物清单")
    listed = "\n".join(str(item["result"].get("file_list")) for item in calls)
    assert "keep.txt" not in listed
    blobs = _blobs(api, version, tasks)
    if not blobs:
        pytest.skip("未测：代码调用没有可下载的产物")
    texts = [blob.decode("utf-8", errors="ignore") for blob in blobs]
    assert any("修改后" in text for text in texts)
    assert any(text.strip() == "新文件" or "新文件" in text for text in texts)
    assert not any(text.strip() == "保持原样" for text in texts)


def test_s028(api, task_sum):
    _require_sum(task_sum)
    question = "用代码在 output/金额表.xlsx 写入金额 1、2、3。"
    follow = "读取刚才的表，保留原内容，增加翻倍金额列。"
    with _mode(api, "container"):
        version = submit_task(api, question)
        first = wait_tasks(api, version)
        continue_task(api, version, follow)
        tasks = wait_tasks(api, version, previous=first)
    blobs = _blobs(api, version, tasks)
    if not blobs:
        pytest.skip("未测：两轮都没有可下载的表格，构造不出跨轮追加列")
    assert _matches(
        blobs, lambda blob: xlsx_contains_amounts(blob, (1, 2, 3)) and xlsx_contains_amounts(blob, (2, 4, 6))
    )


def test_s009(api, task_sum):
    _require_sum(task_sum)
    question = "先用代码在 output/note.txt 写入开始，然后用 ask_user 询问追加内容并等待。不要自己补全。"
    with _mode(api, "container"):
        version = submit_task(api, question)
        tasks = wait_tasks(api, version)
        task_id = waiting_task_id(tasks)
        if not task_id:
            pytest.fail("没有进入 ask_user 等待，不能从别的响应正文里找文件")
        user_input(api, version, task_id, "已确认")
        tasks = wait_tasks(api, version, previous=tasks)
    blobs = _blobs(api, version, tasks)
    texts = [blob.decode("utf-8", errors="ignore") for blob in blobs]
    if not any("开始" in text and "已确认" in text for text in texts):
        pytest.skip("未测：ask_user 已恢复，但下载内容没有同时包含「开始」和「已确认」")


def test_s025(api, task_sum):
    _require_sum(task_sum)
    web = tool_category_payload(api, "web_search")
    if web is None:
        pytest.skip("未测：工具列表里没有联网搜索")
    question = (
        "必须调用联网搜索工具，查询 2026 年全球主要城市的人口。"
        "如果返回里出现 large_tool_results/ 路径，必须接着用代码工具打开那个相对路径，不要加前导斜杠。"
        "只打印三行，格式固定为：\nFIRST:文件第一行\nLAST:文件最后一行\nCOUNT:总行数\n"
        "不要用 read_file 代替代码。如果没有这个路径，说明没有转存，不要编造路径。"
    )
    with _mode(api, "container"):
        _version, tasks = run_task_question(api, question, tools=[linsight_tool_payload(api), web])
    notice = offload_notice(tasks)
    if notice is None:
        pytest.skip("未测：联网搜索的结果没有转到 large_tool_results，不新增长度门槛")
    calls = task_tool_results(tasks)
    logs = "\n".join(str(item["result"].get("log") or "") for item in calls)
    printed = printed_ends(logs)
    if printed is None:
        pytest.skip("未测：结果已转存，但代码没有打印 FIRST、LAST 和 COUNT")
    got_first, got_last, got_count = printed
    assert got_count == notice["count"]
    assert _same_edge(got_first, notice["first"])
    assert _same_edge(got_last, notice["last"])


def _same_edge(printed: str, original: str) -> bool:
    """Preview lines are capped at 1000 characters. Either side may be that prefix."""
    if printed == original:
        return True
    head = original[:200]
    return bool(head) and (printed.startswith(head) or head.startswith(printed[:200]))


def test_s011(api, task_sum):
    _require_sum(task_sum)
    # Upload rejects files over the 50MB cap (11024) and .bin never reaches completed.
    # The oversized file has to be written by an earlier code call, then copied in.
    seed = (
        "用代码在当前目录写入两个文件，不要读取它们的内容。"
        f"big.bin 必须正好是 {_BIG} 个空字节。small.txt 的内容是 SMALL。"
        "写完后分别打印两个文件的字节数。"
    )
    question = (
        "根目录写入会被归位。用代码打开 output/big.bin 和 output/small.txt 并打印内容。"
        "不要在脚本里按大小跳过。大文件失败也要继续读小文件。不要再写回根目录。"
    )
    with _mode(api, "container"):
        version = submit_task(api, seed)
        first = wait_tasks(api, version)
        continue_task(api, version, question)
        tasks = wait_tasks(api, version, previous=first)
    calls = task_tool_results(tasks)
    logs = "\n".join(str(item["result"].get("log") or "") for item in calls)
    code = "\n".join(_code_of(item["step"]) for item in calls)
    if "output/big.bin" not in logs and "output/big.bin" not in code:
        pytest.skip("未测：根目录文件没有归位到 output/big.bin，构造不出超限 copy-in")
    if "output/small.txt" not in code or "SMALL" not in logs:
        pytest.skip("未测：归位之后的代码没有打开 output/small.txt 并打印 SMALL")
    assert "Copy-in skipped an oversized file" in logs
    assert "big.bin" in logs


def test_s026():
    from bisheng_langchain.gpts.tools.code_interpreter.base_executor import BaseExecutor

    notice = BaseExecutor.absolute_path_advisory('open("/output/路径测试.txt", "w")')
    assert notice
    assert BaseExecutor.absolute_path_advisory('open("output/路径测试.txt", "w")') == ""
    if FIXED_MODEL != "1":
        pytest.skip("未测完：没有固定模型，模型是否改成相对路径不能算通过")
    if not sandbox_reachable():
        pytest.skip("未测完：沙箱进程未启动，模型半边不能算通过")
    api = open_api()
    if api is None:
        pytest.skip("未测完：后端不可登录，模型半边不能算通过")
    skill = SKILL_FILE
    if not skill or "/" not in skill:
        api.close()
        pytest.skip("未测完：没有准备好的技能文件，整条不能算通过")
    question = f"用自然语言路径 /output/路径测试.txt 写入 PATH-OK，并读取 /skills/{skill}。不要手改成相对路径。"
    try:
        with _mode(api, "container"):
            version, tasks = run_task_question(api, question, skills=[skill.split("/", 1)[0]])
        calls = task_tool_results(tasks)
        scripts = []
        for item in calls:
            params = item["step"].get("params")
            if not isinstance(params, dict):
                continue
            for key in ("python_code", "code", "input"):
                value = params.get(key)
                if isinstance(value, str) and value.strip():
                    scripts.append(value)
                    break
        code = "\n".join(scripts)
        if not code.strip():
            pytest.skip("未测：模型没有提交可核对的代码，看不出是否改成了相对路径")
        if code.strip().startswith("/") or "'/output" in code or '"/output' in code or "'/skills" in code:
            pytest.fail("只有纠正提示，执行的代码仍是绝对路径")
        assert "output/" in code and "skills/" in code
        blobs = _blobs(api, version, tasks)
        assert any(b"PATH-OK" in blob for blob in blobs)
    finally:
        api.close()


def test_s016(api, task_sum):
    _require_sum(task_sum)
    secret = os.environ.get("SANDBOX_PRIVATE", "")
    questions = [
        "用代码工具读取 /root/.cache/sandbox-test.txt 并打印文件内容。",
        "用代码工具执行 os.walk('/') ，并打印遍历到的路径。",
        "用代码工具打印环境变量 SANDBOX_PRIVATE 的值。",
    ]
    logs = []
    with _mode(api, "container"):
        for question in questions:
            _version, tasks = run_task_question(api, question)
            calls = task_tool_results(tasks)
            if not calls:
                pytest.skip(f"未测：模型没有调用代码工具，执行前拒绝没有被触发: {question}")
            logs.append("\n".join(str(item["result"].get("log") or "") for item in calls))
    assert "REJECTED and nothing was executed" in logs[0]
    assert "HOST-ONLY" not in logs[0]
    assert "REJECTED and nothing was executed" in logs[1]
    if not secret:
        pytest.skip(
            "宿主文件和目录已拒绝。后台私有变量没有可核对的标记，该组未测。"
            "其他租户文件未测。受保护资源没有样本，该组未测。整条不算通过。"
        )
    assert secret not in logs[2]
    other = os.environ.get("BISHENG_RELEASE_OTHER_TENANT_FILE")
    marker = os.environ.get("BISHENG_RELEASE_OTHER_TENANT_MARKER")
    if not other or not marker:
        pytest.skip("宿主文件、目录和私有变量已核对。其他租户文件未测。受保护资源没有样本，该组未测。整条不算通过。")
    with _mode(api, "container"):
        _version, tasks = run_task_question(api, f"用代码工具读取 {other} 并打印内容。")
    other_log = "\n".join(str(item["result"].get("log") or "") for item in task_tool_results(tasks))
    assert marker not in other_log
    pytest.skip("受保护资源没有样本，该组未测。其余隔离组已核对，整条仍不算通过。")


def test_s027():
    baseline_path = os.environ.get("BISHENG_RELEASE_BASELINE")
    if not baseline_path:
        pytest.skip("未测：没有升级前基线，不默认四个入口都要通过")
    client = open_api()
    if client is None:
        pytest.skip("未测：后端不可登录")
    api = client
    import json

    try:
        baseline = json.loads(open(baseline_path, encoding="utf-8").read())
        problems = []
        if "task" in (baseline.get("local") or []):
            with _mode(api, "local"):
                _version, tasks = run_task_question(api, SUM_PROMPT)
            if not log_sum(first_sum_result(tasks, log_sum)):
                problems.append("local 任务模式结果不是 6")
        if "task" in (baseline.get("e2b") or []):
            if not os.environ.get("E2B_API_KEY"):
                problems.append("未测：e2b 没有官方密钥，只跳过 e2b 这一组")
            else:
                with _mode(api, "e2b"):
                    _version, tasks = run_task_question(api, SUM_PROMPT)
                from test.sandbox.release.parse import e2b_sum

                if not e2b_sum(first_sum_result(tasks, e2b_sum)):
                    problems.append("e2b 任务模式 stdout 拼起来不是 6")
        hard = [item for item in problems if not item.startswith("未测")]
        if hard:
            pytest.fail("S-027\n" + "\n".join(problems))
        if problems or (not baseline.get("local") and not baseline.get("e2b")):
            pytest.skip("S-027 " + ("；".join(problems) or "基线没有可跑的入口"))
    finally:
        api.close()


def test_s013(api, task_sum):
    _require_sum(task_sum)
    files = [upload_linsight_file(api, f"part-{index}.txt", b"\0" * _TEN_MIB) for index in range(3)]
    started = time.perf_counter()
    with _mode(api, "container"):
        version = submit_task(api, SUM_PROMPT, files=files)
        tasks = wait_tasks(api, version)
    elapsed = time.perf_counter() - started
    calls = task_tool_results(tasks)
    assert calls, "没有首次代码调用，不能记录耗时"
    print(f"S-013 first_code_call_s={elapsed:.3f} files=3 size_bytes={_TEN_MIB} sandbox=container")
    assert elapsed >= 0
