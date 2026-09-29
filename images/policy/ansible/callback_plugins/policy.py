"""Quiet, secret-safe output and machine-readable drift status for the CLI."""
import json
import os
from pathlib import Path

from ansible.plugins.callback import CallbackBase


class CallbackModule(CallbackBase):
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = "stdout"
    CALLBACK_NAME = "policy"

    def v2_runner_on_ok(self, result):
        if result._result.get("changed"):
            prefix = "drift" if os.environ.get("POLICY_CHECK") == "1" else "changed"
            self._display.display(f"{prefix}: {result._task.get_name()}")

    def v2_runner_on_failed(self, result, ignore_errors=False):
        # Static task names only: arguments, loop items, diffs, and messages can
        # contain host credentials, even when an upstream module fails.
        message = result._task.get_name()
        # This local module emits only fixed, value-free validation errors.
        if result._task.action in ('policy_inputs', 'policy_state_inputs') and result._result.get('policy_error'):
            message += ': ' + result._result['policy_error']
        self._display.error(f"infrastructure-policy: {message}", wrap_text=False)

    def v2_runner_on_unreachable(self, result):
        self.v2_runner_on_failed(result)

    def v2_playbook_on_stats(self, stats):
        changed = sum(stats.summarize(host)["changed"] for host in stats.processed)
        Path(os.environ["POLICY_STATUS_FILE"]).write_text(json.dumps({"changed": changed}))
