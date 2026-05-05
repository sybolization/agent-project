"""Test Cases - Structured test case definitions for Agent-Loop."""

from dataclasses import dataclass
from typing import Literal, Optional


@dataclass
class TestCase:
    name: str
    difficulty: Literal["simple", "medium", "hard"]
    user_input: str
    expected_tools: list[str]
    expected_skills: list[str]
    validation_criteria: list[str]
    description: str = ""
    timeout_seconds: int = 120


TEST_CASES: list[TestCase] = [
    TestCase(
        name="bilibili_hot_videos",
        difficulty="simple",
        user_input="看看B站的热门视频有什么",
        expected_tools=["load_skill", "opencli"],
        expected_skills=["smart-search"],
        validation_criteria=[
            "成功加载 smart-search skill",
            "执行 opencli bilibili hot 命令",
            "返回热门视频列表",
            "列表包含视频标题和链接",
        ],
        description="测试单平台信息获取能力，验证 Tool/Skill 使用是否正确",
        timeout_seconds=240,
    ),
    TestCase(
        name="xiaohongshu_curling_iron",
        difficulty="hard",
        user_input="帮我看看小红书上有哪些卷发棒值得购买",
        expected_tools=["load_skill", "load_reference", "opencli"],
        expected_skills=["smart-search"],
        validation_criteria=[
            "成功加载 smart-search skill",
            "执行搜索相关命令",
            "筛选和总结结果",
            "返回推荐列表，包含产品名称、价格、评价",
            "多轮迭代完成复杂任务",
        ],
        description="测试复杂搜索与筛选能力，验证规划、执行、上下文管理效果",
        timeout_seconds=300,
    ),
    TestCase(
        name="zhihu_hot_topics",
        difficulty="simple",
        user_input="知乎上现在有什么热门话题",
        expected_tools=["load_skill", "opencli"],
        expected_skills=["smart-search"],
        validation_criteria=[
            "成功加载 skill",
            "执行 opencli zhihu hot 命令",
            "返回热门话题列表",
        ],
        description="测试单平台信息获取能力",
        timeout_seconds=240,
    ),
    TestCase(
        name="github_python_trending",
        difficulty="medium",
        user_input="帮我看看 GitHub 上最热门的 Python 项目",
        expected_tools=["load_skill", "opencli"],
        expected_skills=["smart-search"],
        validation_criteria=[
            "成功加载 skill",
            "执行搜索命令",
            "返回项目列表，包含项目名、stars、描述",
            "结果按热度排序",
        ],
        description="测试跨平台搜索和筛选能力",
        timeout_seconds=300,
    ),
    TestCase(
        name="hackernews_top_stories",
        difficulty="simple",
        user_input="Hacker News 上有什么热门技术文章",
        expected_tools=["load_skill", "opencli"],
        expected_skills=["smart-search"],
        validation_criteria=[
            "成功加载 skill",
            "执行 opencli hn top 命令",
            "返回热门技术文章列表",
        ],
        description="测试 opencli hn 命令执行",
        timeout_seconds=240,
    ),
    TestCase(
        name="weibo_hot_search",
        difficulty="simple",
        user_input="微博热搜上有什么话题",
        expected_tools=["load_skill", "opencli"],
        expected_skills=["smart-search"],
        validation_criteria=[
            "成功加载 skill",
            "执行 opencli weibo hot 命令",
            "返回热搜话题列表",
        ],
        description="测试微博热搜获取",
        timeout_seconds=240,
    ),
    TestCase(
        name="multi_platform_comparison",
        difficulty="hard",
        user_input="帮我对比一下 B站和知乎上关于 AI 话题的讨论热度",
        expected_tools=["load_skill", "opencli"],
        expected_skills=["smart-search"],
        validation_criteria=[
            "成功加载 skill",
            "执行多个平台的搜索命令",
            "收集两个平台的数据",
            "对比分析并给出结论",
            "多轮迭代完成复杂任务",
        ],
        description="测试跨平台对比分析能力，验证上下文管理",
        timeout_seconds=300,
    ),
]


def get_test_case(name: str) -> Optional[TestCase]:
    for case in TEST_CASES:
        if case.name == name:
            return case
    return None


def get_test_cases_by_difficulty(difficulty: str) -> list[TestCase]:
    return [case for case in TEST_CASES if case.difficulty == difficulty]


def get_simple_test_cases() -> list[TestCase]:
    return get_test_cases_by_difficulty("simple")


def get_medium_test_cases() -> list[TestCase]:
    return get_test_cases_by_difficulty("medium")


def get_hard_test_cases() -> list[TestCase]:
    return get_test_cases_by_difficulty("hard")
