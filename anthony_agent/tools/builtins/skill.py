"""SkillTool — 按需加载全局技能指令"""

import json
from pathlib import Path
from dataclasses import dataclass

from anthony_agent.tools.base import BaseTool, ToolDefinition, ToolResult

SKILLS_DIR = Path.home() / ".anthony" / "skills"

_TOOL_DESCRIPTION = """\
按需加载一个预定义的技能（skill），将其指令注入当前对话。

技能是一组针对特定任务的详细指令集（可能包含工具链、脚本、文档等资源），加载后严格按其中的指令行事。
只在你判断当前任务需要某个技能时才调用。

注意：技能可能涉及运行代码或安装依赖，执行时使用虚拟环境、uv run、npx 等隔离方式，不要污染系统全局环境。"""


@dataclass
class SkillInfo:
    """一个已发现的技能的元信息。"""
    name: str           # 技能名称（slug）
    description: str    # 简短描述
    skill_dir: Path     # 技能目录路径
    skill_file: Path    # SKILL.md 文件路径


def _parse_frontmatter(text: str) -> dict[str, str]:
    """解析 SKILL.md 开头的 YAML frontmatter（简易实现，只取 key: value）。"""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    meta = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    return meta


def _list_skills() -> list[SkillInfo]:
    """扫描技能目录，支持两种格式：
    1. 目录形式：<slug>-<version>/SKILL.md（+ _meta.json）
    2. 单文件形式：<name>.md（向后兼容）
    """
    if not SKILLS_DIR.is_dir():
        return []
    skills: list[SkillInfo] = []
    seen_names: set[str] = set()

    # 1) 扫描目录形式的技能
    for d in sorted(SKILLS_DIR.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        skill_file = d / "SKILL.md"
        if not skill_file.is_file():
            continue

        # 从 _meta.json 读取 slug
        name = d.name  # 默认用目录名
        meta_file = d / "_meta.json"
        if meta_file.is_file():
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                name = meta.get("slug", name)
            except Exception:
                pass

        # 从 SKILL.md frontmatter 读取 description
        desc = ""
        try:
            content = skill_file.read_text(encoding="utf-8")
            fm = _parse_frontmatter(content)
            desc = fm.get("description", "")
            # 如果 frontmatter 里有 name，优先使用
            if fm.get("name"):
                name = fm["name"]
        except Exception:
            desc = "(无法读取)"

        if name not in seen_names:
            seen_names.add(name)
            skills.append(SkillInfo(name=name, description=desc, skill_dir=d, skill_file=skill_file))

    # 2) 扫描顶层 .md 文件（向后兼容）
    for f in sorted(SKILLS_DIR.glob("*.md")):
        name = f.stem
        if name in seen_names:
            continue
        desc = ""
        try:
            content = f.read_text(encoding="utf-8")
            fm = _parse_frontmatter(content)
            desc = fm.get("description", "")
            if not desc:
                # 取第一行非空内容作为描述
                for line in content.splitlines():
                    stripped = line.strip().lstrip("#").strip()
                    if stripped:
                        desc = stripped
                        break
        except Exception:
            desc = "(无法读取)"
        seen_names.add(name)
        skills.append(SkillInfo(name=name, description=desc, skill_dir=SKILLS_DIR, skill_file=f))

    return skills


def _find_skill(name: str) -> SkillInfo | None:
    """按名称查找技能。"""
    for s in _list_skills():
        if s.name == name:
            return s
    return None


class SkillTool(BaseTool):
    """按需加载全局技能指令"""

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="skill",
            description=_TOOL_DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "要加载的技能名称",
                    },
                },
                "required": ["name"],
            },
        )

    async def execute(self, name: str) -> ToolResult:
        skill = _find_skill(name)
        if skill is None:
            available = [s.name for s in _list_skills()]
            hint = f"可用技能：{', '.join(available)}" if available else "当前无可用技能"
            return ToolResult(
                content=f"技能 '{name}' 不存在。{hint}",
                is_error=True,
            )
        try:
            content = skill.skill_file.read_text(encoding="utf-8")
        except Exception as e:
            return ToolResult(content=f"读取技能文件失败：{e}", is_error=True)

        # 列出技能目录下的其他资源文件（排除 SKILL.md 和 _meta.json）
        extra_files: list[str] = []
        if skill.skill_dir != SKILLS_DIR:  # 目录形式的技能才列资源
            for f in sorted(skill.skill_dir.iterdir()):
                if f.name in ("SKILL.md", "_meta.json") or f.name.startswith("."):
                    continue
                extra_files.append(str(f))

        parts = [f"已加载技能 [{name}]，请严格按照以下指令行事：\n\n{content}"]
        if extra_files:
            parts.append(f"\n\n技能目录：{skill.skill_dir}")
            parts.append(f"额外资源文件：{', '.join(extra_files)}")
            parts.append("如需使用这些资源，可直接通过上述路径读取。")

        return ToolResult(content="\n".join(parts))

    def context_injection(self) -> str | None:
        """将可用技能列表注入系统提示词。"""
        skills = _list_skills()
        if not skills:
            return "# 技能\n当前没有可用技能。用户可在 ~/.anthony/skills/ 下添加技能目录来定义技能。"
        lines = ["# 可用技能（通过 skill 工具加载）"]
        for s in skills:
            lines.append(f"- **{s.name}**：{s.description}")
        lines.append("\n当你判断当前任务适合使用某个技能时，调用 `skill` 工具加载它。")
        return "\n".join(lines)
