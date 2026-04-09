"""Anthony Agent — 入口"""

import argparse

from src.client import OpenAIClient
from src.tools import ToolRegistry
from src.tools.builtins import BUILTIN_TOOLS
from src.agent import Agent
from src.memory import SessionManager
from src.prompts import build_system_prompt
from src.ui import AgentApp


def main():
    parser = argparse.ArgumentParser(description="Anthony Agent")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--resume", metavar="SESSION_ID", nargs="?", const="latest",
        help="恢复指定会话（不带值则恢复最近会话）",
    )
    group.add_argument("--new", action="store_true", help="创建新会话")
    args = parser.parse_args()

    session_mgr = SessionManager()
    if args.new:
        session_id = session_mgr.create_session()
    elif args.resume and args.resume != "latest":
        session_id = session_mgr.init(session_id=args.resume)
    else:
        session_id = session_mgr.init()

    registry = ToolRegistry()
    registry.register_many([tool() for tool in BUILTIN_TOOLS])

    agent = Agent(
        client=OpenAIClient(),
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