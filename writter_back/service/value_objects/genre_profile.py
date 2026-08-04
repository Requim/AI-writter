"""Authoritative genre taxonomy and prompt strategy profiles."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from service.value_objects.novel_type import NovelType


@dataclass(frozen=True)
class GenreOption:
    """Selectable genre refinement option."""

    value: str
    label: str
    description: str = ""


@dataclass(frozen=True)
class GenreProfile:
    """Genre taxonomy plus AIGC strategy axes for prompt rendering."""

    value: str
    label: str
    description: str
    subgenres: tuple[GenreOption, ...]
    reader_experiences: tuple[GenreOption, ...]
    pace_options: tuple[GenreOption, ...]
    prompt_axes: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


PACE_OPTIONS = (
    GenreOption("hook_dense", "强钩子快节奏", "高频转折，章节开合都给出明确压力。"),
    GenreOption("balanced", "起伏均衡", "推进、铺垫和情绪回响保持稳定比例。"),
    GenreOption("slow_burn", "慢热蓄压", "延长铺垫和心理变化，阶段性释放张力。"),
    GenreOption("episodic", "单元推进", "用单元事件持续兑现核心类型快感。"),
)


GENRE_PROFILES: tuple[GenreProfile, ...] = (
    GenreProfile(
        value=NovelType.SUSPENSE.value,
        label="悬疑",
        description="围绕谜团、线索、误导和真相回收建立阅读驱动力。",
        subgenres=(
            GenreOption("cold_case", "旧案重启", "历史伤口被新证据重新打开。"),
            GenreOption("fair_play", "本格推理", "线索公平呈现，读者可同步推理。"),
            GenreOption("social_suspense", "社会派悬疑", "案件背后牵出制度、阶层或伦理压力。"),
            GenreOption("psychological_suspense", "心理悬疑", "认知偏差和心理防御推动谜团。"),
        ),
        reader_experiences=(
            GenreOption("clue_puzzle", "线索推理", "持续获得可验证线索和误导。"),
            GenreOption("truth_shock", "真相震荡", "阶段性反转改变读者对事实的理解。"),
            GenreOption("emotional_echo", "情感回响", "真相揭开后兑现人物关系和创伤余波。"),
        ),
        pace_options=PACE_OPTIONS,
        prompt_axes={
            "reader_promise": "线索、误导、嫌疑关系和阶段性真相必须持续推进。",
            "plot_engine": "用证据链和认知差驱动剧情，不靠作者突然揭晓。",
            "style_constraints": "叙述克制，细节可验证，少解释动机，多呈现判断。",
            "chapter_focus": "每章至少改变线索、嫌疑、风险或主角认知之一。",
            "review_focus": "检查线索公平性、误导合理性和真相阶梯是否兑现。",
            "avoid_solutions": ["突发黑影", "梦境解释", "陌生人突然自白", "作者视角硬反转"],
        },
    ),
    GenreProfile(
        value=NovelType.SCI_FI.value,
        label="科幻",
        description="从核心科学假设出发，推演技术边界和社会后果。",
        subgenres=(
            GenreOption("near_future", "近未来", "现实技术继续演化后的社会切面。"),
            GenreOption("space_opera", "星际冒险", "文明尺度上的探索、冲突和选择。"),
            GenreOption("ai_society", "AI社会", "智能系统改变身份、劳动和权力结构。"),
            GenreOption("wasteland_rebuild", "废土重建", "灾后秩序与资源分配重塑文明。"),
        ),
        reader_experiences=(
            GenreOption("concept_wonder", "概念震撼", "核心设定带来新鲜认知冲击。"),
            GenreOption("speculative_logic", "设定推演", "规则变化产生连锁后果。"),
            GenreOption("civilization_cost", "文明代价", "选择背后有制度和伦理成本。"),
        ),
        pace_options=PACE_OPTIONS,
        prompt_axes={
            "reader_promise": "持续兑现设定奇观、推演后果和文明层面的选择成本。",
            "plot_engine": "让技术边界、资源限制和社会制度共同制造冲突。",
            "style_constraints": "术语服务因果，避免堆概念；每个设定都要产生行动后果。",
            "chapter_focus": "每章暴露一项规则、代价或社会后果。",
            "review_focus": "检查科学假设、限制、代价和剧情后果是否闭合。",
            "avoid_solutions": ["万能科技", "术语堆砌", "无代价升级", "规则临时改写"],
        },
    ),
    GenreProfile(
        value=NovelType.ROMANCE.value,
        label="言情",
        description="以关系变化、情绪张力和亲密兑现驱动阅读期待。",
        subgenres=(
            GenreOption("sweet_romance", "甜宠", "关系稳定升温，冲突服务亲密感。"),
            GenreOption("slow_burn_romance", "慢热拉扯", "用误解、克制和试探推动关系。"),
            GenreOption("second_chance", "破镜重圆", "旧伤和新选择共同考验复合可能。"),
            GenreOption("workplace_romance", "职场情感", "职业利益与私人情感交叉施压。"),
        ),
        reader_experiences=(
            GenreOption("emotional_tension", "情感拉扯", "靠潜台词、误判和选择制造张力。"),
            GenreOption("intimacy_payoff", "亲密兑现", "关键行动证明关系变化。"),
            GenreOption("mutual_healing", "互相治愈", "双方缺口被看见并付出代价修补。"),
        ),
        pace_options=PACE_OPTIONS,
        prompt_axes={
            "reader_promise": "持续兑现关系阶段、情绪递进和亲密行动。",
            "plot_engine": "让欲望、误解、现实阻力和旧伤推动关系变化。",
            "style_constraints": "重潜台词和选择，少用抽象情绪说明替代互动。",
            "chapter_focus": "每章必须改变关系距离、信任程度或情感风险。",
            "review_focus": "检查情绪递进、关系代价和亲密兑现是否可感。",
            "avoid_solutions": ["无代价误会", "强行撒糖", "单方工具人", "只虐不变"],
        },
    ),
    GenreProfile(
        value=NovelType.FANTASY.value,
        label="奇幻",
        description="用异世界规则、奇观探索和命运选择建立史诗感。",
        subgenres=(
            GenreOption("epic_fantasy", "史诗奇幻", "多势力和命运主线逐卷展开。"),
            GenreOption("dark_fantasy", "暗黑奇幻", "力量诱惑伴随道德和生存代价。"),
            GenreOption("magic_academy", "学院魔法", "学习、竞争和规则探索并进。"),
            GenreOption("portal_fantasy", "异世穿越", "外来视角冲击陌生秩序。"),
        ),
        reader_experiences=(
            GenreOption("wonder_exploration", "奇观探索", "持续发现陌生规则和地域。"),
            GenreOption("power_discovery", "力量发现", "能力边界随代价逐步展开。"),
            GenreOption("destiny_choice", "命运抉择", "个人选择影响更大秩序。"),
        ),
        pace_options=PACE_OPTIONS,
        prompt_axes={
            "reader_promise": "持续兑现奇观、规则发现、力量代价和命运压力。",
            "plot_engine": "让世界规则、势力目标和能力限制共同驱动冲突。",
            "style_constraints": "奇观描写必须服务选择、风险或关系，不做静态设定展览。",
            "chapter_focus": "每章推进一项规则理解、势力关系或能力代价。",
            "review_focus": "检查世界规则是否稳定，奇观是否参与剧情。",
            "avoid_solutions": ["临时魔法解围", "设定说明过载", "力量无代价", "势力动机空泛"],
        },
    ),
    GenreProfile(
        value=NovelType.WUXIA.value,
        label="武侠",
        description="以江湖规矩、师承恩怨和侠义选择组织冲突。",
        subgenres=(
            GenreOption("jianghu_grudge", "江湖恩怨", "旧仇新债推动人物抉择。"),
            GenreOption("sect_conflict", "门派争斗", "师承、规矩和利益冲突交错。"),
            GenreOption("wuxia_mystery", "侠义探案", "江湖规则中追索真相。"),
            GenreOption("martial_growth", "武学成长", "招式、心性和江湖责任共同升级。"),
        ),
        reader_experiences=(
            GenreOption("chivalric_choice", "侠义选择", "义利之间做出有代价的判断。"),
            GenreOption("duel_payoff", "交锋兑现", "武学风格和人格在交手中显形。"),
            GenreOption("grudge_resolution", "恩怨了结", "关系债和旧案逐步清算。"),
        ),
        pace_options=PACE_OPTIONS,
        prompt_axes={
            "reader_promise": "持续兑现江湖规矩、武学交锋、恩怨因果和侠义选择。",
            "plot_engine": "让门派利益、师承债务和人格底线制造冲突。",
            "style_constraints": "招式写法体现性格与局势，不把武侠写成换皮玄幻。",
            "chapter_focus": "每章改变一项江湖关系、名声、债务或武学认知。",
            "review_focus": "检查江湖规矩、师承逻辑和侠义代价是否成立。",
            "avoid_solutions": ["法术化武功", "无规矩江湖", "空喊侠义", "招式流水账"],
        },
    ),
    GenreProfile(
        value=NovelType.XIANXIA.value,
        label="仙侠",
        description="以境界体系、道心考验和资源争夺推动长期升级。",
        subgenres=(
            GenreOption("cultivation_progression", "修仙升级", "境界突破和资源争夺递进。"),
            GenreOption("sect_survival", "宗门求存", "宗门利益与个人道途互相牵制。"),
            GenreOption("daoheart_trial", "道心问道", "力量增长伴随价值考验。"),
            GenreOption("immortal_politics", "仙门权谋", "仙门秩序、血脉和资源暗战。"),
        ),
        reader_experiences=(
            GenreOption("level_payoff", "升级兑现", "突破带来能力和地位变化。"),
            GenreOption("daoheart_pressure", "道心考验", "选择影响道途和人格边界。"),
            GenreOption("resource_rivalry", "资源争夺", "灵脉、法宝和传承引发博弈。"),
        ),
        pace_options=PACE_OPTIONS,
        prompt_axes={
            "reader_promise": "持续兑现境界推进、资源竞争、道心代价和因果清算。",
            "plot_engine": "让修行资源、宗门规则、因果代价和对手目标共同施压。",
            "style_constraints": "力量必须有边界和代价，突破要来自积累与选择。",
            "chapter_focus": "每章推进境界认知、资源格局、道心压力或宗门关系。",
            "review_focus": "检查境界体系、资源逻辑和突破代价是否稳定。",
            "avoid_solutions": ["临场开挂", "境界通胀", "法宝万能", "天降传承无代价"],
        },
    ),
    GenreProfile(
        value=NovelType.URBAN.value,
        label="都市",
        description="以现实资源、人情规则和身份差制造现代冲突。",
        subgenres=(
            GenreOption("workplace_game", "职场博弈", "组织规则和职业利益持续施压。"),
            GenreOption("urban_power", "都市异能", "异常能力进入现实秩序。"),
            GenreOption("family_business", "家族商战", "亲缘、资本和声誉互相牵制。"),
            GenreOption("realistic_emotion", "现实情感", "生活压力推动关系变化。"),
        ),
        reader_experiences=(
            GenreOption("status_reversal", "身份翻转", "地位、资源或认知发生逆转。"),
            GenreOption("realistic_game", "现实博弈", "规则内的取舍与反击。"),
            GenreOption("social_pressure", "人情压力", "关系网和现实成本逼迫选择。"),
        ),
        pace_options=PACE_OPTIONS,
        prompt_axes={
            "reader_promise": "持续兑现身份差、资源博弈、现实压力和阶段性反击。",
            "plot_engine": "让职业、金钱、人情、阶层和制度规则产生实际阻力。",
            "style_constraints": "现代细节要准确具体，避免空泛霸总和无摩擦爽点。",
            "chapter_focus": "每章改变资源、关系、舆论、职位或现实选择空间。",
            "review_focus": "检查现实规则、资源流动和人物处境是否可信。",
            "avoid_solutions": ["空泛霸总", "无成本翻盘", "工具人反派", "现实规则缺席"],
        },
    ),
    GenreProfile(
        value=NovelType.HISTORY.value,
        label="历史",
        description="在时代制度、信息速度和阶层边界内推动人物命运。",
        subgenres=(
            GenreOption("court_intrigue", "朝堂权谋", "制度、人事和派系互相制衡。"),
            GenreOption("historical_turn", "历史转折", "人物卷入关键时代节点。"),
            GenreOption("war_strategy", "战争谋略", "补给、地形和军心决定胜负。"),
            GenreOption("commoner_rise", "小人物逆袭", "阶层缝隙中争取生存和尊严。"),
        ),
        reader_experiences=(
            GenreOption("institution_pressure", "制度压力", "时代规则限制每个选择。"),
            GenreOption("strategy_win", "谋略胜利", "信息、资源和人心布局兑现。"),
            GenreOption("era_destiny", "时代命运", "个人命运与历史浪潮互相映照。"),
        ),
        pace_options=PACE_OPTIONS,
        prompt_axes={
            "reader_promise": "持续兑现制度压力、谋略布局、时代限制和命运回响。",
            "plot_engine": "让礼法、官制、军政、阶层和信息传播速度制造冲突。",
            "style_constraints": "称谓、礼制和物质条件要服从时代，不使用现代口吻偷懒。",
            "chapter_focus": "每章改变权力关系、信息优势、制度处境或民心筹码。",
            "review_focus": "检查史实边界、制度逻辑和时代语言是否稳定。",
            "avoid_solutions": ["现代观念直塞", "制度背景乱用", "信息传播超速", "称谓礼制混乱"],
        },
    ),
    GenreProfile(
        value=NovelType.HORROR.value,
        label="惊悚",
        description="通过安全感剥夺、空间限制和未知压力制造持续恐惧。",
        subgenres=(
            GenreOption("closed_space", "封闭空间", "有限空间内安全边界不断收缩。"),
            GenreOption("folk_horror", "民俗怪谈", "地方禁忌和仪式规则制造恐惧。"),
            GenreOption("psychological_horror", "心理惊悚", "感知不可靠和心理裂缝升级。"),
            GenreOption("survival_escape", "逃生求生", "资源耗尽与追逐压力推进剧情。"),
        ),
        reader_experiences=(
            GenreOption("safety_loss", "安全感剥夺", "熟悉秩序逐步失效。"),
            GenreOption("fear_escalation", "恐惧升级", "异常从边缘迹象变成直接威胁。"),
            GenreOption("escape_pressure", "逃生压力", "每个选择都缩短安全余量。"),
        ),
        pace_options=PACE_OPTIONS,
        prompt_axes={
            "reader_promise": "持续兑现安全感剥夺、异常升级和逃生代价。",
            "plot_engine": "让空间限制、规则禁忌、资源消耗和认知不确定共同施压。",
            "style_constraints": "恐惧来自可感细节和选择后果，不只依赖惊吓名词。",
            "chapter_focus": "每章降低一层安全感，暴露一条规则或付出一次逃生代价。",
            "review_focus": "检查恐惧递进、规则稳定和安全边界变化是否明确。",
            "avoid_solutions": ["单纯吓人", "无规则怪物", "反复黑影", "梦醒解释"],
        },
    ),
    GenreProfile(
        value=NovelType.COMEDY.value,
        label="喜剧",
        description="用人物执念、身份错位和包袱回收产生轻快推进力。",
        subgenres=(
            GenreOption("identity_mismatch", "身份错位", "角色认知差带来连续误会。"),
            GenreOption("workplace_comedy", "职场喜剧", "组织规则和个人执念互相碰撞。"),
            GenreOption("family_comedy", "家庭喜剧", "亲密关系里的误会和和解。"),
            GenreOption("absurd_adventure", "荒诞冒险", "荒诞事件仍遵守内部因果。"),
        ),
        reader_experiences=(
            GenreOption("contrast_laugh", "反差笑点", "身份、语气或行动预期被反转。"),
            GenreOption("misunderstanding_chain", "误会升级", "误解形成连锁后果。"),
            GenreOption("warm_release", "温暖释放", "笑点之后兑现关系或成长。"),
        ),
        pace_options=PACE_OPTIONS,
        prompt_axes={
            "reader_promise": "持续兑现反差、误会升级、包袱回收和温暖落点。",
            "plot_engine": "让人物执念、信息差和社会场景规则制造笑点后果。",
            "style_constraints": "笑点必须推动剧情或关系，不写可删除的孤立段子。",
            "chapter_focus": "每章建立、升级或回收一个包袱，并推动实际状态变化。",
            "review_focus": "检查笑点机制、误会链和剧情推进是否互相绑定。",
            "avoid_solutions": ["只写段子", "低级谐音堆砌", "无后果误会", "人物降智"],
        },
    ),
)


_PROFILES_BY_VALUE = {profile.value: profile for profile in GENRE_PROFILES}
_PROFILES_BY_LABEL = {profile.label: profile for profile in GENRE_PROFILES}


def get_genre_profile(value: str) -> GenreProfile | None:
    """Resolve a profile by stored value or display label."""
    key = str(value or "").strip()
    return _PROFILES_BY_VALUE.get(key) or _PROFILES_BY_LABEL.get(key)


def get_genre_taxonomy() -> list[dict[str, Any]]:
    """Return serializable genre taxonomy in display order."""
    return [profile.to_dict() for profile in GENRE_PROFILES]
