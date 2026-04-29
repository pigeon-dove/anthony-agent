from src.tools.builtins.read_file import ReadFileTool
from src.tools.builtins.write_file import WriteFileTool
from src.tools.builtins.edit_file import EditFileTool
from src.tools.builtins.multi_edit import MultiEditTool
from src.tools.builtins.bash import BashTool
from src.tools.builtins.bash_background import BackgroundBashTool
from src.tools.builtins.ls import LsTool
from src.tools.builtins.glob import GlobTool
from src.tools.builtins.grep import GrepTool
from src.tools.builtins.think import ThinkTool
from src.tools.builtins.web_search import WebSearchTool
from src.tools.builtins.web_fetch import WebFetchTool
from src.tools.builtins.task import TaskTool
from src.tools.builtins.skill import SkillTool

# 无参构造的内置工具类（不含 TaskTool，它需要额外依赖注入）
BUILTIN_TOOLS = [
    ReadFileTool, WriteFileTool, EditFileTool, MultiEditTool,
    BashTool, BackgroundBashTool, LsTool, GlobTool, GrepTool,
    ThinkTool, WebSearchTool, WebFetchTool,
    SkillTool,
]
