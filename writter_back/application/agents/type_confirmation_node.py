"""类型确认节点 - 强制用户输入，使用interrupt"""
import logging
logger = logging.getLogger("uvicorn")
from langgraph.types import interrupt, Command
from typing import Literal
from application.schemas.agent_state import NovelAgentState


def type_confirmation_node(state: NovelAgentState) -> Command[Literal["title_node"]]:
    """
    类型确认节点 - 强制用户输入小说类型
    使用 interrupt() 暂停，等待用户通过 API 提供 novel_type
    """
    logger.info(f"{'='*60}")
    logger.info(f"【类型确认节点】进入 | 小说类型={state.get('novel_type', '未设置')}")
    # 如果已设置（通过 resume 传入），直接通过
    if state.get("novel_type"):
        logger.info(f"【类型确认节点】跳过 -> 书名节点 | 类型已设置: {state['novel_type']}")
        logger.info(f"{'='*60}")
        return Command(goto="title_node")
    
    # 可选类型列表
    available_types = {
        "suspense": "悬疑",
        "sci_fi": "科幻", 
        "romance": "言情",
        "fantasy": "奇幻",
        "wuxia": "武侠",
        "xianxia": "仙侠",
        "urban": "都市",
        "history": "历史",
        "horror": "恐怖",
        "comedy": "喜剧"
    }
    
    # interrupt 暂停执行，将信息返回给调用方（API层）
    user_input = interrupt({
        "action": "require_novel_type",
        "message": "请选择小说类型（必选）",
        "available_types": available_types,
        "description": "小说类型是创作的基础，将影响后续所有内容的风格和走向"
    })
    
    # 验证用户输入
    if user_input not in available_types:
        logger.info(f"【类型确认节点】输入无效({user_input})，重新等待用户输入")
        return Command(goto="type_confirmation_node")
    
    logger.info(f"【类型确认节点】用户选择了类型: {available_types.get(user_input, user_input)} -> 书名节点")
    logger.info(f"{'='*60}")
    return Command(
        goto="title_node",
        update={"novel_type": user_input}
    )
