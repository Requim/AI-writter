"""修正提示词"""


def build_user_instruction_revision_prompt(
    instructions: str,
    current_content: str,
    chapter_title: str,
) -> str:
    """用户指令修正的提示词"""
    return f"""
请根据以下用户指令修正章节内容：

用户修正指令：{instructions}

原章节内容：
{current_content}

章节细纲：
{chapter_title}
"""


def build_auto_fix_revision_prompt(
    issues_text: str,
    current_content: str,
    chapter_title: str,
) -> str:
    """AI自动修正的提示词"""
    return f"""
请根据以下问题列表修正章节内容，确保修正后无逻辑问题：

问题列表：
{issues_text}

原章节内容：
{current_content}

章节细纲：
{chapter_title}

要求：
1. 修正所有提到的问题
2. 保持章节字数在3000-6000字之间
3. 保持原有的写作风格和情节走向
"""


def format_issues_for_prompt(issues: list) -> str:
    """将问题列表格式化为提示词文本"""
    return "\n".join([
        f"- [{issue.get('type', 'unknown')}] "
        f"{issue.get('location', '')}: "
        f"{issue.get('description', '')} "
        f"(建议: {issue.get('suggestion', '')})"
        for issue in issues
    ])


def build_revision_system_prompt() -> str:
    """修正的系统提示词"""
    return "你是专业的小说编辑，擅长修正逻辑问题和改进内容质量。"


REVISION_TEMPERATURE = 0.5
