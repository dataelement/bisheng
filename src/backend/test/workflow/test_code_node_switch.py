"""The Code node is off unless an operator turns it on (issue #2189).

The node runs user-supplied Python with the backend's own privileges and there
is no execution sandbox yet, so a deployment must not be exposed by default.
The gate sits where the node is *built*: parsing the code already executes it,
so a check in the run path would fire after the code had run.
"""

from unittest.mock import MagicMock, patch

import pytest

from bisheng.core.config.settings import WorkflowConf
from bisheng.utils.exceptions import IgnoreException
from bisheng.workflow.nodes.code import code as code_node


def _conf(**kwargs) -> WorkflowConf:
    return WorkflowConf(**kwargs)


def test_the_node_is_off_when_nothing_is_configured():
    assert _conf().code_node_enabled is False


@pytest.mark.parametrize("value", ["true", "True", 1, "yes", None, {}, "false"])
def test_only_a_real_boolean_true_turns_it_on(value):
    """A typo in the config must not be the thing that opens code execution."""
    assert _conf(code_node_enabled=value).code_node_enabled is False


def test_an_explicit_true_turns_it_on():
    assert _conf(code_node_enabled=True).code_node_enabled is True


def _with_conf(enabled: bool):
    settings = MagicMock()
    settings.get_workflow_conf.return_value = _conf(code_node_enabled=enabled)
    return patch.object(code_node, "bisheng_settings", settings)


def test_a_disabled_node_refuses_before_reading_any_code():
    with _with_conf(False), pytest.raises(IgnoreException) as raised:
        code_node.assert_code_node_enabled()

    # The runner sees this as the failure reason, so it has to say where to fix it.
    assert "code_node_enabled" in str(raised.value)


def test_an_enabled_node_passes_the_gate():
    with _with_conf(True):
        code_node.assert_code_node_enabled()


@pytest.fixture
def bare_base_node():
    """The gate is all this test cares about; BaseNode's own wiring is not."""
    with patch.object(code_node.BaseNode, "__init__", lambda self, *args, **kwargs: None):
        yield


def test_building_a_node_is_refused_while_the_switch_is_off(bare_base_node):
    """Covers both entry points: a workflow run and the run_once debug call
    build the node the same way."""
    with _with_conf(False), pytest.raises(IgnoreException):
        code_node.CodeNode()


def test_the_gate_runs_before_the_code_is_parsed(bare_base_node):
    with _with_conf(False), patch.object(code_node, "CodeParser") as parser:
        with pytest.raises(IgnoreException):
            code_node.CodeNode()

    parser.assert_not_called()
