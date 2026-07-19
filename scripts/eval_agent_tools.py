#!/usr/bin/env python
"""Agent 工具选择评测：对话 agent 在真实系统提示词与工具清单下选没选对工具。

方法论与 eval_recall.py 一致——评测走与线上完全相同的路径：同一份
SYSTEM_PROMPT、同一份 TOOL_DEFINITIONS、同一个 DeepSeek API 与线上默认温度。
只评"决策"不评"执行"：捕获模型的首个工具调用（或不调用）与参数，
不真正执行工具，因此零副作用、无需数据库。

用法：
    python scripts/eval_agent_tools.py [--trials 3] [--temperature 0.7] \
        [--report docs/agent-tool-eval-report.md]

指标：
    - 工具选择正确率：首个工具调用命中期望集合（no_tool 用例要求不调用）
    - 误调用率：no_tool 用例中模型仍发起工具调用的比例
    - 参数正确率：工具选对的样本中，期望参数（如 candidate_id、job_id）也正确的比例
    - 稳定性：多 trial 下同一用例结果不一致的用例数（线上温度非 0，抖动真实存在）

无 DEEPSEEK_API_KEY 直接报错退出，不做静默降级。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agent_hub.agents.global_part_time.chat_service import SYSTEM_PROMPT  # noqa: E402
from agent_hub.agents.global_part_time.chat_tools import TOOL_DEFINITIONS  # noqa: E402

CASES_PATH = Path(__file__).resolve().parent / "agent_tool_eval_cases.json"
NO_TOOL = "no_tool"
VALID_TOOLS = {t["function"]["name"] for t in TOOL_DEFINITIONS} | {NO_TOOL}


def load_cases(path: Path = CASES_PATH) -> list[dict[str, Any]]:
    cases = json.loads(path.read_text(encoding="utf-8"))["cases"]
    for case in cases:
        unknown = set(case["expected_tools"]) - VALID_TOOLS
        if unknown:
            raise ValueError(f"case {case['id']} expects unknown tools: {unknown}")
    return cases


def build_messages(case: dict[str, Any]) -> list[dict[str, Any]]:
    """与 chat_service.build_llm_messages 相同的上下文构造方式。"""
    system_content = SYSTEM_PROMPT
    candidate_id = case.get("candidate_id")
    if candidate_id:
        system_content += f"\n\n当前候选人 ID: {candidate_id}。调用工具时请使用此 ID。"
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_content}]
    messages.extend(case.get("history", []))
    messages.append({"role": "user", "content": case["user_message"]})
    return messages


def extract_decision(message: Any) -> tuple[str, dict[str, Any]]:
    """从响应消息中提取首个工具名与参数；未调用工具返回 (no_tool, {})。"""
    tool_calls = getattr(message, "tool_calls", None)
    if not tool_calls:
        return NO_TOOL, {}
    first = tool_calls[0]
    try:
        args = json.loads(first.function.arguments or "{}")
    except json.JSONDecodeError:
        args = {}
    return first.function.name, args


def check_args(case: dict[str, Any], args: dict[str, Any]) -> tuple[bool, list[str]]:
    """校验 expected_args：null 只要求存在；'$CANDIDATE' 替换为绑定的候选人 ID。"""
    problems: list[str] = []
    for key, expected in (case.get("expected_args") or {}).items():
        if key not in args:
            problems.append(f"missing arg {key}")
            continue
        if expected is None:
            continue
        if expected == "$CANDIDATE":
            expected = case.get("candidate_id")
        actual = args[key]
        if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
            if float(actual) != float(expected):
                problems.append(f"{key}={actual!r} != {expected!r}")
        elif actual != expected:
            problems.append(f"{key}={actual!r} != {expected!r}")
    return not problems, problems


def score_sample(case: dict[str, Any], tool: str, args: dict[str, Any]) -> dict[str, Any]:
    tool_ok = tool in case["expected_tools"]
    args_ok: bool | None = None
    problems: list[str] = []
    # 参数只在选中了"带参数期望的那个工具"时才有意义
    if tool_ok and tool != NO_TOOL and case.get("expected_args"):
        args_ok, problems = check_args(case, args)
    return {
        "tool": tool,
        "args": args,
        "tool_ok": tool_ok,
        "args_ok": args_ok,
        "problems": problems,
    }


def run_case(client: Any, model: str, case: dict[str, Any], temperature: float) -> dict[str, Any]:
    response = client.chat.completions.create(
        model=model,
        messages=build_messages(case),
        tools=TOOL_DEFINITIONS,
        temperature=temperature,
        max_tokens=512,
    )
    tool, args = extract_decision(response.choices[0].message)
    return score_sample(case, tool, args)


def summarize(cases: list[dict[str, Any]], results: dict[str, list[dict[str, Any]]]) -> dict:
    samples = [(c, r) for c in cases for r in results[c["id"]]]
    total = len(samples)
    tool_correct = sum(1 for _, r in samples if r["tool_ok"])
    no_tool_samples = [(c, r) for c, r in samples if c["expected_tools"] == [NO_TOOL]]
    false_calls = sum(1 for _, r in no_tool_samples if not r["tool_ok"])
    arg_samples = [r for _, r in samples if r["args_ok"] is not None]
    by_category: dict[str, list[bool]] = defaultdict(list)
    for case, r in samples:
        by_category[case["category"]].append(r["tool_ok"])
    unstable = [cid for cid, rs in results.items() if len({r["tool_ok"] for r in rs}) > 1]
    return {
        "total_samples": total,
        "tool_accuracy": tool_correct / total if total else 0.0,
        "false_call_rate": false_calls / len(no_tool_samples) if no_tool_samples else 0.0,
        "args_accuracy": (
            sum(1 for r in arg_samples if r["args_ok"]) / len(arg_samples) if arg_samples else None
        ),
        "by_category": {cat: sum(oks) / len(oks) for cat, oks in sorted(by_category.items())},
        "unstable_cases": unstable,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=int, default=1, help="每个用例的重复次数")
    parser.add_argument("--temperature", type=float, default=0.7, help="与线上一致的默认温度")
    parser.add_argument("--report", type=Path, default=None, help="把结果写入 markdown 报告")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    load_dotenv()
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        print("DEEPSEEK_API_KEY 未配置，评测终止", file=sys.stderr)
        return 1
    from openai import OpenAI

    client = OpenAI(
        api_key=api_key, base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    )
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    cases = load_cases()
    jobs = [(case, trial) for case in cases for trial in range(args.trials)]
    results: dict[str, list[dict[str, Any]]] = defaultdict(list)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(run_case, client, model, case, args.temperature): case for case, _ in jobs
        }
        for future, case in futures.items():
            results[case["id"]].append(future.result())

    summary = summarize(cases, results)
    print(
        f"\n== Agent 工具选择评测（{len(cases)} 用例 × {args.trials} trials，"
        f"temperature={args.temperature}，model={model}）=="
    )
    print(f"工具选择正确率: {summary['tool_accuracy']:.1%}")
    print(f"no_tool 误调用率: {summary['false_call_rate']:.1%}")
    if summary["args_accuracy"] is not None:
        print(f"参数正确率（工具选对的样本中）: {summary['args_accuracy']:.1%}")
    print("分类别正确率:")
    for cat, acc in summary["by_category"].items():
        print(f"  {cat:<20} {acc:.1%}")
    if summary["unstable_cases"]:
        print(f"多 trial 结果不稳定的用例: {summary['unstable_cases']}")

    failures = [
        (case, r)
        for case in cases
        for r in results[case["id"]]
        if not r["tool_ok"] or r["args_ok"] is False
    ]
    if failures:
        print("\n失败样本:")
        for case, r in failures:
            reason = "; ".join(r["problems"]) if r["problems"] else f"picked {r['tool']}"
            print(f"  [{case['id']}] expect {case['expected_tools']} -> {reason}")

    if args.report:
        args.report.write_text(
            render_report(cases, results, summary, args, model), encoding="utf-8"
        )
        print(f"\n报告已写入 {args.report}")
    return 0


def render_report(cases, results, summary, args, model) -> str:
    lines = [
        "# Agent 工具选择评测报告",
        "",
        f"> 生成命令：`python scripts/eval_agent_tools.py --trials {args.trials} "
        f"--temperature {args.temperature}`，model={model}。",
        "> 评测走线上同一路径（同一系统提示词、同一工具清单、同一 API 与温度），",
        "> 只评首个工具决策、不执行工具，零副作用可复现。",
        "",
        "## 总览",
        "",
        f"- 用例数：{len(cases)}（每用例 {args.trials} trials，共 {summary['total_samples']} 样本）",
        f"- 工具选择正确率：**{summary['tool_accuracy']:.1%}**",
        f"- no_tool 误调用率：**{summary['false_call_rate']:.1%}**",
    ]
    if summary["args_accuracy"] is not None:
        lines.append(f"- 参数正确率（工具选对的样本中）：**{summary['args_accuracy']:.1%}**")
    lines += ["", "## 分类别正确率", "", "| 类别 | 正确率 |", "|---|---|"]
    lines += [f"| {cat} | {acc:.1%} |" for cat, acc in summary["by_category"].items()]
    if summary["unstable_cases"]:
        lines += ["", f"多 trial 不稳定用例：{', '.join(summary['unstable_cases'])}"]
    failures = [
        (case, r)
        for case in cases
        for r in results[case["id"]]
        if not r["tool_ok"] or r["args_ok"] is False
    ]
    lines += ["", "## 失败样本", ""]
    if failures:
        lines += ["| 用例 | 期望 | 实际 | 问题 |", "|---|---|---|---|"]
        for case, r in failures:
            problem = "; ".join(r["problems"]) or "工具选择错误"
            lines.append(
                f"| {case['id']} | {'/'.join(case['expected_tools'])} | {r['tool']} | {problem} |"
            )
    else:
        lines.append("无。")
    lines += [
        "",
        "## 已知局限",
        "",
        "- 只评首个工具决策，不评多轮工具链与最终回答质量；",
        "- 线上温度非 0，结果存在抖动，建议以 3 trials 的均值为准；",
        "- 用例为人工构造的单轮/短历史场景，真实多轮长对话的表现需线上反馈补充。",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
