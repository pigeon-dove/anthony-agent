from anthony_agent.tools.builtins.read_file import ReadFileTool
from anthony_agent.tools.builtins.write_file import WriteFileTool
from anthony_agent.tools.builtins.edit_file import EditFileTool
from anthony_agent.tools.builtins.multi_edit import MultiEditTool
from anthony_agent.tools.builtins.bash import BashTool
from anthony_agent.tools.builtins.bash_background import BackgroundBashTool
from anthony_agent.tools.builtins.ls import LsTool
from anthony_agent.tools.builtins.glob import GlobTool
from anthony_agent.tools.builtins.grep import GrepTool
from anthony_agent.tools.builtins.think import ThinkTool
from anthony_agent.tools.builtins.web_search import WebSearchTool
from anthony_agent.tools.builtins.web_fetch import WebFetchTool
from anthony_agent.tools.builtins.task import TaskTool
from anthony_agent.tools.builtins.skill import SkillTool

# 无参构造的内置工具类（不含 TaskTool，它需要额外依赖注入）
BUILTIN_TOOLS = [
    ReadFileTool, WriteFileTool, EditFileTool, MultiEditTool,
    BashTool, BackgroundBashTool, LsTool, GlobTool, GrepTool,
    ThinkTool, WebSearchTool, WebFetchTool,
    SkillTool,
]
