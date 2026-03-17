from src.tools.builtins.read_file import ReadFileTool
from src.tools.builtins.write_file import WriteFileTool

# 所有内置工具实例列表，直接传给 registry.register_many()
BUILTIN_TOOLS = [ReadFileTool(), WriteFileTool()]
