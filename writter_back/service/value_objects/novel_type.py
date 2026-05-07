"""小说类型枚举"""
from enum import Enum


class NovelType(str, Enum):
    """小说类型"""
    SUSPENSE = "suspense"           # 悬疑
    SCI_FI = "sci_fi"               # 科幻
    ROMANCE = "romance"             # 言情
    FANTASY = "fantasy"            # 奇幻
    WUXIA = "wuxia"                # 武侠
    XIANXIA = "xianxia"            # 仙侠
    URBAN = "urban"                # 都市
    HISTORY = "history"             # 历史
    HORROR = "horror"              # 恐怖
    COMEDY = "comedy"               # 喜剧
    
    @classmethod
    def get_display_name(cls, value: str) -> str:
        """获取显示名称"""
        display_names = {
            cls.SUSPENSE.value: "悬疑",
            cls.SCI_FI.value: "科幻",
            cls.ROMANCE.value: "言情",
            cls.FANTASY.value: "奇幻",
            cls.WUXIA.value: "武侠",
            cls.XIANXIA.value: "仙侠",
            cls.URBAN.value: "都市",
            cls.HISTORY.value: "历史",
            cls.HORROR.value: "恐怖",
            cls.COMEDY.value: "喜剧",
        }
        return display_names.get(value, value)
    
    @classmethod
    def get_all_types(cls) -> dict:
        """获取所有类型"""
        return {t.value: t.get_display_name(t.value) for t in cls}
