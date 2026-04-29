"""Anthony Agent — 入口"""

import argparse

from anthony_agent.client import OpenAIClient
from anthony_agent.tools import ToolRegistry
from anthony_agent.tools.builtins import BUILTIN_TOOLS, TaskTool
from anthony_agent.agent import Agent
from anthony_agent.memory import SessionManager
from anthony_agent.prompts import build_system_prompt
from anthony_agent.ui import AgentApp


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
    parser = argparse.ArgumentParser(description="Anthony Agent")
    subparsers = parser.add_subparsers(dest="subcommand")
    subparsers.add_parser("list", help="列出所有历史会话")

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