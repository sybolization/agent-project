"""技能管理器 - 渐进式技能加载"""

import logging
import re
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


SKILLS_DIR = Path(__file__).parent

logger = logging.getLogger(__name__)


@dataclass
class SkillMeta:
    """技能元数据，从SKILL.md frontmatter中提取"""
    name: str
    description: str
    path: Path
    category: Optional[str] = None  # 所属类别名称


@dataclass
class SkillCategory:
    """技能类别"""
    name: str  # 类别名称，如 "feishu", "opencli"
    description: str  # 类别用途说明
    path: Path  # 类别目录路径
    skills: list[SkillMeta] = field(default_factory=list)  # 该类别下的技能列表


class SkillManager:
    """技能渐进式加载管理器，支持懒加载"""
    
    def __init__(self, skills_dir: Optional[Path] = None):
        self.skills_dir = skills_dir or SKILLS_DIR
        self._loaded_skills: dict[str, str] = {}
        self._loaded_references: dict[tuple[str, str], str] = {}
        self._skill_metas: Optional[list[SkillMeta]] = None
        self._categories: Optional[list[SkillCategory]] = None
        self._disabled_categories: set[str] = set()
        
        if not self.skills_dir.exists():
            logger.warning(f"Skills directory does not exist: {self.skills_dir}")
        else:
            logger.debug(f"Skills directory initialized: {self.skills_dir}")
    
    def _scan_categories(self) -> list[SkillCategory]:
        """扫描技能类别
        
        类别检测逻辑：
        1. 扫描 skills_dir 下的直接子目录
        2. 检查每个子目录是否有 skills 子目录（如 feishu/skills/）
        3. 如果存在 CATEGORY.md 文件，从中读取 name 和 description
        4. 否则使用目录名作为 name，生成默认 description
        """
        if self._categories is not None:
            return self._categories
        
        categories = []
        
        # 扫描 skills_dir 下的直接子目录
        for category_dir in self.skills_dir.iterdir():
            if not category_dir.is_dir():
                continue
            
            # 检查是否是有效的类别目录
            # 条件：存在 skills 子目录 或 直接包含 SKILL.md 的子目录
            skills_subdir = category_dir / "skills"
            has_skills = False
            
            if skills_subdir.exists() and skills_subdir.is_dir():
                # 检查 skills 子目录下是否有技能
                has_skills = any(skills_subdir.rglob("SKILL.md"))
            else:
                # 检查直接子目录下是否有技能
                has_skills = any(category_dir.glob("*/SKILL.md"))
            
            if not has_skills:
                continue
            
            # 读取类别信息
            category_file = category_dir / "CATEGORY.md"
            if category_file.exists():
                name, description = self._extract_category_info(category_file)
            else:
                name = category_dir.name
                description = self._generate_category_description(name)
            
            categories.append(SkillCategory(
                name=name,
                description=description,
                path=category_dir,
                skills=[]
            ))
        
        self._categories = categories
        return categories
    
    def _extract_category_info(self, category_file: Path) -> tuple[str, str]:
        """从 CATEGORY.md 文件中提取类别信息
        
        支持从 YAML frontmatter 中提取 name 和 description
        """
        try:
            content = category_file.read_text(encoding="utf-8")
            frontmatter_match = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
            
            if frontmatter_match:
                frontmatter_text = frontmatter_match.group(1)
                frontmatter = yaml.safe_load(frontmatter_text)
                
                if isinstance(frontmatter, dict):
                    name = frontmatter.get('name', category_file.parent.name)
                    description = frontmatter.get('description', '')
                    return str(name), str(description)
        except Exception:
            pass
        
        # 回退：使用目录名
        return category_file.parent.name, self._generate_category_description(category_file.parent.name)
    
    def _generate_category_description(self, category_name: str) -> str:
        """生成默认的类别描述"""
        category_descriptions = {
            'feishu': '飞书/Lark 相关技能，包括多维表格、日历、文档、云盘、即时通讯等功能',
            'opencli': 'OpenCLI 相关技能，包括浏览器操作、桌面操作、智能搜索等功能',
        }
        
        if category_name in category_descriptions:
            return category_descriptions[category_name]
        
        return f'{category_name} 类别的技能集合'
    
    def _scan_skills(self) -> list[SkillMeta]:
        """递归扫描所有技能并从frontmatter提取元数据
        
        支持多层目录结构，例如：
        - skills/weather/SKILL.md
        - skills/feishu/skills/lark-base/SKILL.md
        """
        if self._skill_metas is not None:
            return self._skill_metas
        
        # 确保类别已扫描
        categories = self._scan_categories()
        category_map = {cat.path: cat for cat in categories}
        
        metas = []
        # 递归扫描所有包含SKILL.md的目录
        for skill_file in self.skills_dir.rglob("SKILL.md"):
            skill_dir = skill_file.parent
            try:
                content = skill_file.read_text(encoding="utf-8")
                # 使用相对于skills_dir的路径作为name，支持多层目录
                name = str(skill_dir.relative_to(self.skills_dir)).replace("\\", "/")
                description = self._extract_description(content)
                
                # 如果没有description，生成默认描述
                if not description:
                    description = self._generate_default_description(name, content)
                
                # 确定技能所属类别
                category_name = self._determine_skill_category(skill_dir, category_map)
                
                skill_meta = SkillMeta(
                    name=name,
                    description=description,
                    path=skill_file,
                    category=category_name
                )
                metas.append(skill_meta)
                
                # 将技能添加到对应类别
                if category_name:
                    for cat in categories:
                        if cat.name == category_name:
                            cat.skills.append(skill_meta)
                            break
            except Exception:
                continue
        
        self._skill_metas = metas
        return metas
    
    def _determine_skill_category(self, skill_dir: Path, category_map: dict[Path, SkillCategory]) -> Optional[str]:
        """确定技能所属的类别
        
        Args:
            skill_dir: 技能目录路径
            category_map: 类别路径到类别的映射
            
        Returns:
            类别名称，如果无法确定则返回 None
        """
        # 从技能目录向上查找匹配的类别
        current = skill_dir.parent
        
        while current != self.skills_dir and current != current.parent:
            if current in category_map:
                return category_map[current].name
            
            # 检查是否在某个类别的 skills 子目录下
            if current.name == "skills":
                parent = current.parent
                if parent in category_map:
                    return category_map[parent].name
            
            current = current.parent
        
        return None
    
    def _extract_description(self, content: str) -> str:
        """从YAML frontmatter中提取描述
        
        支持多种YAML多行字符串格式：
        - description: 单行文本
        - description: |  (保留换行)
            多行文本
        - description: >  (折叠换行)
            多行文本
        """
        frontmatter_match = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
        if not frontmatter_match:
            return ""
        
        frontmatter_text = frontmatter_match.group(1)
        
        try:
            frontmatter = yaml.safe_load(frontmatter_text)
            if isinstance(frontmatter, dict) and 'description' in frontmatter:
                desc = frontmatter['description']
                if isinstance(desc, str):
                    # 清理多余的空白字符，但保留段落结构
                    lines = desc.strip().split('\n')
                    # 移除每行首尾空白，并过滤空行
                    cleaned_lines = [line.strip() for line in lines if line.strip()]
                    # 将多行合并为一个段落，用空格连接
                    return ' '.join(cleaned_lines)
        except yaml.YAMLError:
            # 如果YAML解析失败，回退到正则表达式提取
            pass
        
        # 回退方案：使用正则表达式提取
        desc_match = re.search(r'^description:\s*(.+)$', frontmatter_text, re.MULTILINE)
        if desc_match:
            return desc_match.group(1).strip()
        
        return ""
    
    def _generate_default_description(self, skill_name: str, content: str) -> str:
        """为缺失description的skill生成默认描述
        
        策略：
        1. 从内容中提取第一个标题后的段落作为描述
        2. 如果没有合适内容，使用格式化的目录名
        """
        # 移除frontmatter
        content_without_frontmatter = re.sub(r'^---\s*\n.*?\n---\s*\n', '', content, flags=re.DOTALL)
        
        # 查找第一个非标题段落
        lines = content_without_frontmatter.split('\n')
        paragraph_lines = []
        in_paragraph = False
        
        for line in lines:
            stripped = line.strip()
            # 跳过空行、标题、引用块、代码块等
            if not stripped:
                if in_paragraph and paragraph_lines:
                    break
                continue
            if stripped.startswith('#') or stripped.startswith('>') or stripped.startswith('```'):
                if in_paragraph and paragraph_lines:
                    break
                continue
            if stripped.startswith('|') or stripped.startswith('-') or stripped.startswith('*'):
                if in_paragraph and paragraph_lines:
                    break
                continue
            
            # 收集段落内容
            in_paragraph = True
            paragraph_lines.append(stripped)
            
            # 限制长度，避免过长
            if len(' '.join(paragraph_lines)) > 150:
                break
        
        if paragraph_lines:
            desc = ' '.join(paragraph_lines)
            # 截断过长的描述
            if len(desc) > 120:
                desc = desc[:117] + '...'
            return desc
        
        # 如果没有找到合适内容，使用格式化的目录名
        return f"Skill: {skill_name.replace('-', ' ').replace('_', ' ').title()}"
    
    def get_skill_descriptions(self) -> list[dict]:
        """获取所有技能描述（轻量级，仅返回描述不返回完整内容）"""
        metas = self._scan_skills()
        return [
            {"name": m.name, "description": m.description, "category": m.category}
            for m in metas
            if m.category is None or m.category not in self._disabled_categories
        ]
    
    def get_categories(self) -> list[SkillCategory]:
        """返回所有启用的类别"""
        # 确保技能已扫描，这样才能正确关联技能到类别
        self._scan_skills()
        categories = self._scan_categories()
        return [cat for cat in categories if cat.name not in self._disabled_categories]
    
    def get_category_index_prompt(self) -> str:
        """返回类别概览提示词"""
        # 确保技能已扫描，这样才能正确统计每个类别的技能数量
        self._scan_skills()
        categories = self._scan_categories()
        
        # 过滤已禁用的类别
        active_categories = [cat for cat in categories if cat.name not in self._disabled_categories]
        
        if not active_categories:
            return "当前没有可用的技能类别。"
        
        # 构建类别列表
        category_list = []
        for i, cat in enumerate(active_categories, 1):
            skill_count = len(cat.skills)
            category_list.append(f"  {i}. {cat.name} ({skill_count} 个技能): {cat.description}")
        
        categories_text = '\n'.join(category_list)
        
        return f"""
可用技能类别 (共 {len(active_categories)} 个):

{categories_text}

使用 get_category_skills_prompt(category_name) 查看特定类别的技能列表。
使用 load_skill(skill_name) 加载技能详细内容。
"""
    
    def get_category_skills_prompt(self, category_name: str) -> str:
        """返回指定类别的技能列表提示词
        
        Args:
            category_name: 类别名称
            
        Returns:
            该类别的技能列表提示词
        """
        if category_name in self._disabled_categories:
            return f"类别 '{category_name}' 已被禁用，不可加载。"
        
        self._scan_skills()
        categories = self._scan_categories()
        
        target_category = None
        for cat in categories:
            if cat.name == category_name:
                target_category = cat
                break
        
        if not target_category:
            return f"未找到类别: {category_name}"
        
        if not target_category.skills:
            return f"类别 {category_name} 下没有技能。"
        
        skills_list = []
        for i, skill in enumerate(target_category.skills, 1):
            desc = skill.description
            if len(desc) > 100:
                desc = desc[:97] + '...'
            skills_list.append(f"  {i}. {skill.name}: {desc}")
        
        skills_text = '\n'.join(skills_list)
        
        return f"""
类别: {target_category.name}
说明: {target_category.description}

技能列表 (共 {len(target_category.skills)} 个):

{skills_text}

使用 load_skill(skill_name) 加载技能详细内容。
每个 skill 可能包含 references/ 子文档，使用 load_reference 加载。
"""
    
    def get_skill_index_prompt(self) -> str:
        """获取技能索引提示词（用于初始上下文）- 显示类别概览"""
        return self.get_category_index_prompt()
    
    def load_skill(self, skill_name: str) -> Optional[str]:
        """加载技能的完整内容（重量级操作）"""
        if skill_name in self._loaded_skills:
            return self._loaded_skills[skill_name]
        
        # 检查技能是否属于已禁用的类别
        metas = self._scan_skills()
        for meta in metas:
            if meta.name == skill_name:
                if meta.category and meta.category in self._disabled_categories:
                    return None
                break
        
        skill_path = self.skills_dir / skill_name / "SKILL.md"
        
        if skill_path.exists():
            content = skill_path.read_text(encoding="utf-8")
            refs = self.list_references(skill_name)
            if refs:
                content += f"\n\n---\n可用的 references: {', '.join(refs)}"
            self._loaded_skills[skill_name] = content
            return content
        
        return None
    
    def load_reference(self, skill_name: str, reference_name: str) -> Optional[str]:
        """加载技能的参考文档"""
        cache_key = (skill_name, reference_name)
        if cache_key in self._loaded_references:
            return self._loaded_references[cache_key]
        
        ref_path = self.skills_dir / skill_name / "references" / f"{reference_name}.md"
        
        if ref_path.exists():
            content = ref_path.read_text(encoding="utf-8")
            self._loaded_references[cache_key] = content
            return content
        
        return None
    
    def list_references(self, skill_name: str) -> list[str]:
        """列出技能可用的参考文档"""
        refs_dir = self.skills_dir / skill_name / "references"
        if refs_dir.exists():
            return [f.stem for f in refs_dir.glob("*.md")]
        return []
    
    def is_skill_loaded(self, skill_name: str) -> bool:
        """检查技能是否已加载"""
        return skill_name in self._loaded_skills
    
    def get_loaded_skills(self) -> list[str]:
        """获取已加载的技能名称列表"""
        return list(self._loaded_skills.keys())
    
    def clear_cache(self):
        """清空已加载技能缓存"""
        self._loaded_skills.clear()
        self._loaded_references.clear()
        self._skill_metas = None
        self._categories = None

    def disable_category(self, category_name: str) -> None:
        """禁用指定类别的技能"""
        self._disabled_categories.add(category_name)

    def enable_category(self, category_name: str) -> None:
        """启用指定类别的技能"""
        self._disabled_categories.discard(category_name)

    def disable_categories(self, category_names: list[str]) -> None:
        """批量禁用类别的技能"""
        for name in category_names:
            self._disabled_categories.add(name)

    def enable_categories(self, category_names: list[str]) -> None:
        """批量启用类别的技能"""
        for name in category_names:
            self._disabled_categories.discard(name)

    def enable_all_categories(self) -> None:
        """启用所有类别的技能"""
        self._disabled_categories.clear()

    def get_disabled_categories(self) -> list[str]:
        """获取已禁用的类别列表"""
        return list(self._disabled_categories)

    def is_category_enabled(self, category_name: str) -> bool:
        """检查类别是否启用"""
        return category_name not in self._disabled_categories
