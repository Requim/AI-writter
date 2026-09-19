"""手动流程应容纳一次完整的十五分钟节点执行。"""

from config import Settings


def test_manual_timeout_defaults_cover_a_full_node():
    fields = Settings.model_fields
    assert fields["WORKFLOW_NODE_TIMEOUT_SECONDS"].default == 900
    assert fields["WORKFLOW_BACKGROUND_NODE_TIMEOUT_SECONDS"].default == 900
    assert fields["WORKFLOW_TIMEOUT_SECONDS"].default > 900
