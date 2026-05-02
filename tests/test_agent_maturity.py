from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from webapi.config import load_execution_policy_config
from webapi.execution_policy import check_command_policy
from webapi.session_store import SessionStore
from webapi.skill_runner import load_skills_registry, run_skill_call


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _expand_eval_expr(expr: str) -> str:
    root = str(_project_root()).replace("\\", "/")
    return (expr or "").replace("__ROOT__", root)


def _expand_policy_cmd(cmd: str, cwd: str) -> str:
    return (cmd or "").replace("__CWD__", cwd)


def _skip_scenario(skip_if: str | None) -> bool:
    if not skip_if:
        return False
    if skip_if == "no_rg":
        return shutil.which("rg") is None
    if skip_if == "needs_gateway":
        return not (
            (os.getenv("OMLXCLI_SEARCH_GATEWAY_URL") or "").strip()
            or (os.getenv("OMLXCLI_SEARXNG_URL") or "").strip()
        )
    if skip_if == "needs_outbound_http":
        return (os.getenv("OMLXCLI_EVAL_SKIP_HTTP") or "").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
    return False


class AgentMaturityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "sessions.db")
        self.store = SessionStore(self.db_path)
        self.session = self.store.create_session(
            title="t",
            workspace_path=self.tmpdir.name,
            model="m",
            api_base="http://127.0.0.1:8000/v1",
            auto_run=True,
        )

    def tearDown(self) -> None:
        del self.store
        self.tmpdir.cleanup()

    def test_agent_trace_roundtrip(self) -> None:
        self.store.add_agent_trace(
            session_id=self.session.id,
            turn_id="turn-1",
            step_index=0,
            action_type="turn_start",
            detail={"k": 1},
        )
        rows = self.store.list_agent_trace(self.session.id, turn_id="turn-1", limit=10)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["action_type"], "turn_start")
        self.assertEqual(rows[0]["detail"]["k"], 1)

    def test_readonly_template_with_strict_mode_uses_strict_mutating(self) -> None:
        """模板 readonly 但显式 mode=strict 时，不应仍使用「全拦截」mutating。"""
        old_tpl = os.environ.pop("OMLXCLI_EXEC_POLICY_TEMPLATE", None)
        old_mode = os.environ.pop("OMLXCLI_EXEC_POLICY_MODE", None)
        old_mut = os.environ.pop("OMLXCLI_EXEC_MUTATING_RE", None)
        try:
            os.environ["OMLXCLI_EXEC_POLICY_TEMPLATE"] = "readonly"
            os.environ["OMLXCLI_EXEC_POLICY_MODE"] = "strict"
            cfg = load_execution_policy_config()
            self.assertEqual(cfg.mode, "strict")
            self.assertNotEqual(cfg.mutating_pattern.strip(), ".+")
        finally:
            for k, v in (
                ("OMLXCLI_EXEC_POLICY_TEMPLATE", old_tpl),
                ("OMLXCLI_EXEC_POLICY_MODE", old_mode),
                ("OMLXCLI_EXEC_MUTATING_RE", old_mut),
            ):
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_execution_policy_template_dev(self) -> None:
        old_tpl = os.environ.pop("OMLXCLI_EXEC_POLICY_TEMPLATE", None)
        old_mode = os.environ.pop("OMLXCLI_EXEC_POLICY_MODE", None)
        old_enf = os.environ.pop("OMLXCLI_EXEC_ENFORCE_WORKSPACE_BOUNDARY", None)
        try:
            os.environ["OMLXCLI_EXEC_POLICY_TEMPLATE"] = "dev"
            os.environ.pop("OMLXCLI_EXEC_POLICY_MODE", None)
            os.environ.pop("OMLXCLI_EXEC_ENFORCE_WORKSPACE_BOUNDARY", None)
            cfg = load_execution_policy_config()
            self.assertEqual(cfg.template, "dev")
            self.assertFalse(cfg.enforce_workspace_boundary)
        finally:
            if old_tpl is not None:
                os.environ["OMLXCLI_EXEC_POLICY_TEMPLATE"] = old_tpl
            else:
                os.environ.pop("OMLXCLI_EXEC_POLICY_TEMPLATE", None)
            if old_mode is not None:
                os.environ["OMLXCLI_EXEC_POLICY_MODE"] = old_mode
            else:
                os.environ.pop("OMLXCLI_EXEC_POLICY_MODE", None)
            if old_enf is not None:
                os.environ["OMLXCLI_EXEC_ENFORCE_WORKSPACE_BOUNDARY"] = old_enf
            else:
                os.environ.pop("OMLXCLI_EXEC_ENFORCE_WORKSPACE_BOUNDARY", None)

    def test_agent_eval_scenarios_file(self) -> None:
        root = Path(__file__).resolve().parent
        path = root / "fixtures" / "agent_eval_scenarios.json"
        scenarios = json.loads(path.read_text(encoding="utf-8"))
        funcs, _ = load_skills_registry()
        self.assertTrue(funcs, "skills 应能加载以跑评测用例")
        for sc in scenarios:
            if _skip_scenario(str(sc.get("skip_if") or "").strip() or None):
                continue
            expr = _expand_eval_expr(str(sc.get("expr") or ""))
            want = int(sc.get("expect_exit", 0))
            ret = run_skill_call(expr, funcs)
            self.assertEqual(
                int(ret["exit_code"]),
                want,
                msg=f"{sc.get('name')}: {ret.get('stderr')}",
            )

    def test_policy_eval_scenarios_file(self) -> None:
        path = Path(__file__).resolve().parent / "fixtures" / "policy_eval_scenarios.json"
        scenarios = json.loads(path.read_text(encoding="utf-8"))
        cwd = self.tmpdir.name
        policy_keys = (
            "OMLXCLI_EXEC_BLOCKLIST_RE",
            "OMLXCLI_EXEC_HIGH_RISK_RE",
            "OMLXCLI_EXEC_MUTATING_RE",
            "OMLXCLI_EXEC_ENFORCE_WORKSPACE_BOUNDARY",
            "OMLXCLI_EXEC_POLICY_TEMPLATE",
            "OMLXCLI_EXEC_POLICY_MODE",
            "OMLXCLI_EXEC_ALLOWLIST_RE",
        )
        saved = {k: os.environ.get(k) for k in policy_keys}
        try:
            for sc in scenarios:
                name = str(sc.get("name") or "")
                for k in policy_keys:
                    os.environ.pop(k, None)
                os.environ["OMLXCLI_EXEC_ENFORCE_WORKSPACE_BOUNDARY"] = "1"
                for ek, ev in (sc.get("env") or {}).items():
                    os.environ[str(ek)] = str(ev)
                cmd = _expand_policy_cmd(str(sc.get("cmd") or ""), cwd)
                confirm_each = bool(sc.get("confirm_each"))
                ok, _msg, need_confirm = check_command_policy(cmd, cwd, confirm_each)
                self.assertEqual(
                    ok,
                    bool(sc.get("expect_ok", True)),
                    msg=f"{name}: policy ok mismatch",
                )
                exp_c = bool(sc.get("expect_confirm", False))
                self.assertEqual(
                    need_confirm,
                    exp_c,
                    msg=f"{name}: need_confirm mismatch",
                )
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_run_skill_call_timeout(self) -> None:
        def _hang() -> str:
            time.sleep(3)
            return "done"

        old = os.environ.get("OMLXCLI_RUN_SKILL_TIMEOUT_SEC")
        os.environ["OMLXCLI_RUN_SKILL_TIMEOUT_SEC"] = "1"
        try:
            ret = run_skill_call("_hang()", {"_hang": _hang})
            self.assertEqual(int(ret["exit_code"]), 1)
            self.assertIn("超时", ret.get("stderr") or "")
        finally:
            if old is None:
                os.environ.pop("OMLXCLI_RUN_SKILL_TIMEOUT_SEC", None)
            else:
                os.environ["OMLXCLI_RUN_SKILL_TIMEOUT_SEC"] = old

    def test_workspace_boundary_blocks_symlink_escape(self) -> None:
        if not hasattr(os, "symlink"):
            self.skipTest("当前环境不支持 symlink")
        root = self.tmpdir.name
        outer = os.path.join(root, "outside")
        os.makedirs(outer, exist_ok=True)
        ws = os.path.join(root, "workspace")
        os.makedirs(ws, exist_ok=True)
        secret = os.path.join(outer, "secret")
        with open(secret, "w", encoding="utf-8") as fh:
            fh.write("x")
        link = os.path.join(ws, "escape")
        try:
            os.symlink(secret, link)
        except OSError:
            self.skipTest("无法创建 symlink（权限或平台限制）")
        cmd = f"touch {link}"
        ok, msg, need_confirm = check_command_policy(cmd, ws, False)
        self.assertFalse(ok, msg)
        self.assertFalse(need_confirm)
