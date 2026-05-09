"""总纲领生成提示词（深度优化版）

设计：单次生成为主，两阶段降级为截断兜底
- Phase 1 (primary): 单次生成完整大纲（含章节），验证 total_chapters == len(chapters）
- Phase 2 (fallback): 若截断则先出宏观总纲，再单独生成章节

优化维度：
1. 人物关系明朗（The Web）：强制冲突对象和关系标签
2. 逻辑严谨性（The Constraint）：力量代价 + 社会矛盾  
3. 章节节奏（The Rhythm）：卷概念 + 节拍点 + 具体事件
4. 风格一致性（The Tone）：细化写作风格要素
"""

import json
from typing import Dict, List, Any


# ==================== Schema 定义 ====================
# 注：实际约束由 Prompt 控制，schema 仅元数据用途
# 所有 LLM 适配器均使用 response_format={"type": "json_object"}

OUTLINE_SCHEMA: Dict[str, str] = {
    "story_background": "string",
    "main_characters": "array",
    "main_plot": "object",
    "chapters": "array",
    "writing_style": "string",
    "total_chapters": "integer",
    "volumes": "array",
}

MACRO_ONLY_SCHEMA: Dict[str, str] = {
    "story_background": "string",
    "main_characters": "array",
    "main_plot": "object",
    "writing_style": "string",
    "total_chapters": "integer",
    "volumes": "array",
}

CHAPTERS_ONLY_SCHEMA: Dict[str, str] = {
    "chapters": "array",
}


def build_outline_prompt(novel_type: str, title: str, summary: str) -> str:
    """
    单次生成完整总纲领（含章节规划）。
    基于用户提供的深度优化结构，整合 4 个优化维度。
    若输出被截断，由调用方检测并降级到两阶段生成。
    """
    return f"""请根据以下基础信息，构建一份逻辑严密、结构宏大且具有强冲突感的小说总纲领。

【基础信息】
类型：{novel_type}
书名：{title}
简介：{summary}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【核心生成要求】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. 逻辑一致性：story_background 必须定义世界观的"核心限制"或"力量代价"，
   所有剧情推进需遵循因果律，不允许逻辑崩坏的情节。

2. 人物关系网：主要人物之间必须存在交叉的利益冲突、情感羁绊或阵营对抗，
   形成稳定的动态关系结构。不能是各自独立的 9 个角色。

3. 章节节拍：以"卷"为宏观组织单元，每 30-50 章为一个卷，
   每卷末安排阶段性高潮和伏笔清算，卷尾留钩子引向下一卷。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【各字段深度约束】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. story_background（800-1500字）必须涵盖：
   (1) 核心地理/势力范围
   (2) 力量体系及其副作用/代价（如：使用魔法会折寿、调查真相会疯掉）
   (3) 社会底层矛盾（根本性的阶级/理念冲突）
   (4) 导致故事爆发的导火索事件

2. main_characters（至少 9 个）每个角色包含：
   - 姓名
   - 性格（2-4个核心特质）
   - 目标：必须是具体且随剧情演进的动态目标
   - 冲突对象：该角色与哪位角色存在本质对抗？（指名道姓）
   - 关系标签：明确标注其在关系网中的定位，如：主角的引路人、隐藏的最终反派、
     被背叛的盟友、亦敌亦友的竞争者、利益暂时一致的敌人等
   ❗ 每个角色至少与 2 个角色存在关系，反对派必须有合理动机

3. main_plot 必须包含"起承转合"：
   - 起（开端）：导火索事件 + 主角如何卷入
   - 承（发展）：冲突升级、各方势力登场
   - 转（高潮）：最大危机/反转/真相揭示
   - 合（结局）：结局以某种方式呼应开头的伏笔

4. chapters（建议 120-300 章）：
   - 以"卷"为逻辑单元组织（对应下面 volumes 定义）
   - 每章包含：theme（主题/一句话概括）、key_events（至少2个具体事件）
   - 每个 key_event 必须是具体细节动作或关键信息揭示
   ❌ 禁止的无效事件："主角继续调查"、"主角继续修炼"
   ✅ 有效事件示例："主角在书房发现一张被撕碎的照片，照片背面有血迹"、
      "揭示幕后黑手就是十年前失踪的消防队长陈建国"
   - 建议每章含 volume_name 字段标注所属卷名

5. writing_style（200-400字）需定义：
   - 叙事视角（第一/第三人称有限/全知/多视角切换）
   - 节奏快慢（前期偏慢营造氛围/中期加快冲突频率）
   - 语言基调（冷峻写实/诗意/黑色幽默/史诗感）
   - 对话风格（简洁有力/啰嗦日常/文雅含蓄）
   - 氛围营造方式

6. volumes（卷规划）每卷包含：
   - volume_name：卷名（如：第一卷 潜龙在渊）
   - volume_number：卷序号
   - start_chapter / end_chapter：起止章节
   - core_conflict：本卷核心冲突
   - main_character_arc：主角在本卷的成长弧线
   - climax_event：本卷高潮事件

7. total_chapters：整数，必须与 chapters 数组长度一致

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【输出 JSON 格式】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{{
    "story_background": "故事背景...",
    "main_characters": [
        {{"姓名": "", "性格": "", "目标": "", "冲突对象": "", "关系标签": ""}}
    ],
    "main_plot": {{"起": "", "承": "", "转": "", "合": ""}},
    "chapters": [
        {{"chapter_number": 1, "theme": "", "key_events": [""], "volume_name": ""}}
    ],
    "writing_style": "写作风格...",
    "total_chapters": 180,
    "volumes": [
        {{"volume_name": "第一卷 潜龙在渊", "volume_number": 1,
          "start_chapter": 1, "end_chapter": 40,
          "core_conflict": "", "main_character_arc": "", "climax_event": ""}}
    ]
}}

⚠️ 重要：total_chapters 必须严格等于 chapters 数组长度。
输出必须是标准 JSON，无解析错误，无截断。
"""


def build_chapters_only_prompt(novel_type: str, title: str, summary: str,
                               macro_outline: Dict[str, Any]) -> str:
    """
    Fallback Phase 2: 仅生成 chapters 数组。
    在单次生成截断时使用，基于宏观总纲补全章节。
    """
    bg = macro_outline.get("story_background", "")[:300]
    chars_summary = _summarize_characters(macro_outline.get("main_characters", []))
    plot_summary = macro_outline.get("main_plot", {})
    total = macro_outline.get("total_chapters", 0)
    volumes = macro_outline.get("volumes", [])
    volumes_text = json.dumps(volumes, ensure_ascii=False, indent=2) if volumes else "无卷规划"

    return f"""请根据宏观总纲，补全完整的章节规划。

【宏观大纲参考】
类型：{novel_type}
书名：{title}
简介摘要：{summary[:200]}
背景摘要：{bg}
人物摘要：{chars_summary}
主线：起={plot_summary.get("起","")[:100]} 承={plot_summary.get("承","")[:100]} 
      转={plot_summary.get("转","")[:100]} 合={plot_summary.get("合","")[:100]}
总章节数：{total}

【卷结构（章节组织框架）】
{volumes_text}

【章节生成规则】
1. 数组长度必须严格等于 {total} 章
2. 每章必须包含：chapter_number（从1开始连续）、theme（主题）、
   key_events（至少2个具体事件，必须有具体动作或信息揭示）
3. 以 volume_name 标注所属卷名，与 volumes 定义一致
4. 卷边界处要有悬念承接（上卷末的钩子在本卷首章应有所体现）
5. 每个 key_event 必须是具体动作或信息揭示：
   ❌ "主角继续调查" ✅ "主角在密室发现半张烧焦的照片"
   ❌ "主角修炼" ✅ "主角第一次施展禁术后左臂出现黑色纹路"

【JSON 输出格式】
{{"chapters": [{{"chapter_number": 1, "theme": "", "key_events": [""], "volume_name": ""}}]}}

确保 chapters 数组长度严格等于 {total}。"""


# ==================== 工具函数 ====================

def _summarize_characters(characters: List[Dict[str, Any]]) -> str:
    """压缩角色列表为摘要"""
    if not characters:
        return "无"
    lines = []
    for c in characters[:10]:
        name = c.get("姓名", c.get("name", "未知"))
        conflict = c.get("冲突对象", c.get("conflict", "?"))
        tag = c.get("关系标签", c.get("relation_tag", "?"))
        lines.append(f"  {name} → 冲突:{conflict} | 标签:{tag}")
    if len(characters) > 10:
        lines.append(f"  ...及其他 {len(characters)-10} 个角色")
    return "\n".join(lines)


def detect_truncation(outline: Dict[str, Any]) -> List[str]:
    """
    检测大纲是否被截断。
    返回检测到的问题列表，空列表 = 无截断。
    """
    issues = []

    # 关键检测：章节数量不一致 → 截断的强信号
    chapters = outline.get("chapters", [])
    total = outline.get("total_chapters", 0)
    if total > 0 and len(chapters) != total:
        issues.append(f"章节数量不一致: total_chapters={total}, 实际生成={len(chapters)}")

    # 角色不足也可能是截断信号
    chars = outline.get("main_characters", [])
    if len(chars) < 9:
        issues.append(f"主要人物不足 9 个（当前 {len(chars)} 个）")

    # 缺失关键字段
    if not outline.get("story_background"):
        issues.append("story_background 为空")
    if not outline.get("writing_style"):
        issues.append("writing_style 为空")

    # 卷结构缺失
    volumes = outline.get("volumes", [])
    if not volumes and total > 0:
        issues.append("volumes 为空")

    return issues


def validate_outline(outline: Dict[str, Any]) -> Dict[str, Any]:
    """验证大纲完整性和质量，返回修复后的大纲+问题列表"""
    issues = detect_truncation(outline)

    # 角色字段完整性检查
    chars = outline.get("main_characters", [])
    required_char_fields = ["姓名", "性格", "目标", "冲突对象", "关系标签"]
    for i, c in enumerate(chars):
        missing = [f for f in required_char_fields if f not in c]
        if missing:
            issues.append(f"角色 {i+1} 缺少字段: {', '.join(missing)}")

    # 章节关键事件质量检查
    vague_patterns = ["继续", "探索", "调查", "修炼", "研究"]
    for ch in outline.get("chapters", []):
        for evt in ch.get("key_events", []):
            for pat in vague_patterns:
                if evt.startswith(pat) or evt.startswith(f"主角{pat}"):
                    issues.append(f"第{ch.get('chapter_number','?')}章事件可能空泛: '{evt[:40]}'")
                    break

    # 卷覆盖检查
    chapters = outline.get("chapters", [])
    volumes = outline.get("volumes", [])
    if chapters and volumes:
        vol_names = [v.get("volume_name", "") for v in volumes]
        for ch in chapters:
            vn = ch.get("volume_name", "")
            if vn and vn not in vol_names:
                issues.append(f"章节 '{ch.get('theme','')}' 的卷名 '{vn}' 未在 volumes 中定义")
                break

    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "is_truncated": len(chapters) > 0 and outline.get("total_chapters", 0) > len(chapters),
    }
