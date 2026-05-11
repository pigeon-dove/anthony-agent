"""Anthony Agent — 入口"""

import argparse
import shutil
from unicodedata import east_asian_width

from anthony_agent.client import OpenAIClient
from anthony_agent.tools import ToolRegistry
from anthony_agent.tools.builtins import BUILTIN_TOOLS, TaskTool
from anthony_agent.tools.builtins.skill import SKILLS_DIR, _list_skills
from anthony_agent.agent import Agent
from anthony_agent.memory import SessionManager
from anthony_agent.prompts import build_system_prompt
from anthony_agent.ui import AgentApp


def _display_width(s: str) -> int:
    """计算字符串在终端的显示宽度（东亚宽字符按2算）。"""
    return sum(2 if east_asian_width(c) in ("W", "F") else 1 for c in s)


def _pad_to_width(s: str, width: int) -> str:
    """按显示宽度右侧填充空格到指定宽度。"""
    pad = width - _display_width(s)
    return s + " " * pad if pad > 0 else s


def _truncate_to_width(s: str, width: int) -> str:
    """按显示宽度截断字符串，超出则末尾补 `…`。"""
    if _display_width(s) <= width:
        return s
    result, cur = [], 0
    limit = width - 1  # 给 `…` 留位置（显示宽度为 1）
    for c in s:
        w = 2 if east_asian_width(c) in ("W", "F") else 1
        if cur + w > limit:
            break
        result.append(c)
        cur += w
    return "".join(result) + "…"


def _cmd_skills() -> None:
    """列出 ~/.anthony/skills/ 下的所有技能。"""
    skills = _list_skills()
    if not skills:
        print(f"当前没有可用技能。可在 {SKILLS_DIR} 下添加技能目录。")
        return

    # 根据终端宽度自适应：desc 列用剩余空间
    term_w = shutil.get_terminal_size((100, 24)).columns
    # name 列宽 = 所有 skill 名称的最大显示宽度（至少 8，最多 30）
    name_w = max(8, min(30, max(_display_width(s.name) for s in skills)))
    desc_w = max(20, term_w - name_w - 2)  # 2 是列间距；下限 20 保证可读

    header = _pad_to_width("Skill", name_w) + "  " + "描述"
    sep = "-" * (name_w + 2 + desc_w)
    print(header)
    print(sep)
    for s in skills:
        desc = _truncate_to_width(s.description or "(无描述)", desc_w)
        print(_pad_to_width(s.name, name_w) + "  " + desc)

    print()
    print(f"↳ 技能目录：{SKILLS_DIR}")


def _cmd_list() -> None:
    """列出当前目录下的所有历史会话。"""
    session_mgr = SessionManager()
    sessions = session_mgr.list_sessions()
    if not sessions:
        print("当前目录下没有历史会话。")
        return

    # 表头
    id_w, cnt_w = 26, 8
    header = f"{'Session ID':<{id_w}}  {'消息数':>{cnt_w}}  最后一条消息"
    sep = "-" * len(header)
    print(header)
    print(sep)
    for s in sessions:
        print(f"{s['session_id']:<{id_w}}  {s['message_count']:>{cnt_w}}  {s['last_preview']}")

    print()
    print("↳ 用 `anthony --resume <Session ID>` 恢复会话")


def main():
    epilog = (
        "Examples:\n"
        "  anthony                       进入默认会话（最近会话或新建）\n"
        "  anthony --new                 创建新会话\n"
        "  anthony --resume              恢复最近一次会话\n"
        "  anthony --resume abc123       恢复指定会话\n"
        "  anthony list                  列出所有历史会话\n"
        "  anthony skills                列出所有可用技能\n"
    )
    parser = argparse.ArgumentParser(
        description="Anthony Agent",
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="subcommand")
    subparsers.add_parser("list", help="列出所有历史会话")
    subparsers.add_parser("skills", help="列出所有可用技能")

    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--resume", metavar="SESSION_ID", nargs="?", const="latest",
        help="恢复指定会话（不带值则恢复最近会话）",
    )
    group.add_argument("--new", action="store_true", help="创建新会话")
    args = parser.parse_args()

    if args.subcommand == "list":
        _cmd_list()
        return
    if args.subcommand == "skills":
        _cmd_skills()
        return

    session_mgr = SessionManager()
    if args.new:
        session_id = session_mgr.create_session()
    elif args.resume and args.resume != "latest":
        session_id = session_mgr.init(session_id=args.resume)
    else:
        session_id = session_mgr.init()

    client = OpenAIClient()
    registry = ToolRegistry()
    registry.register_many([tool() for tool in BUILTIN_TOOLS])
    registry.register(TaskTool(client=client, registry=registry))

    agent = Agent(
        client=client,
        registry=registry,
        system_prompt=build_system_prompt(
            session_id=session_id,
            session_dir=session_mgr.session_dir or "",
        ),
        session_manager=session_mgr,
    )
    agent.load_history()

    AgentApp(agent=agent, session_id=session_id, tool_registry=registry).run()


if __name__ == "__main__":
    main()