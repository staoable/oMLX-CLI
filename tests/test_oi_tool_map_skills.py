"""OI_TOOL_MAP.json 与 `.omlxcli/skills/manifests/skills.json` 全集一致性。"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / ".omlxcli/skills" / "manifests" / "skills.json"
TOOL_MAP = ROOT / "OI_TOOL_MAP.json"
SKILLS_DIR = ROOT / ".omlxcli" / "skills"


def _manifest_skill_names() -> set[str]:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    skills = data.get("skills")
    if not isinstance(skills, dict):
        raise AssertionError("manifest.skills 必须是对象")
    return set(skills.keys())


def _ast_skill_defs_in_file(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        for dec in node.decorator_list:
            name = None
            if isinstance(dec, ast.Name):
                name = dec.id
            elif isinstance(dec, ast.Call):
                fn = dec.func
                if isinstance(fn, ast.Name):
                    name = fn.id
            if name == "skill":
                out.add(node.name)
                break
    return out


def _discovered_skill_funcs_from_repo() -> set[str]:
    """扫描 `.omlxcli/skills/*.py`（排除 `_` 前缀）中 @skill 装饰的顶层函数名。"""
    names: set[str] = set()
    for path in sorted(SKILLS_DIR.glob("*.py")):
        if path.name.startswith("_"):
            continue
        names |= _ast_skill_defs_in_file(path)
    return names


class OiToolMapSkillsTest(unittest.TestCase):
    def test_tool_map_lists_exact_manifest_skills(self) -> None:
        manifest_names = _manifest_skill_names()
        data = json.loads(TOOL_MAP.read_text(encoding="utf-8"))
        self.assertEqual(data.get("scope"), "omlxcli_skills_only")
        skills = data.get("skills")
        self.assertIsInstance(skills, list)
        map_names = {str(s["name"]) for s in skills if isinstance(s, dict) and s.get("name")}
        self.assertEqual(
            map_names,
            manifest_names,
            msg="OI_TOOL_MAP.json 的 skills[].name 必须与 manifests/skills.json 的键集合完全一致",
        )

    def test_each_mapped_skill_has_source_file_on_disk(self) -> None:
        data = json.loads(TOOL_MAP.read_text(encoding="utf-8"))
        for s in data.get("skills") or []:
            if not isinstance(s, dict):
                continue
            fn = str(s.get("source_file") or "")
            self.assertTrue(fn.endswith(".py"), msg=f"{s.get('name')}: source_file 应为 .py")
            p = SKILLS_DIR / fn
            self.assertTrue(p.is_file(), msg=f"{s.get('name')}: 缺少文件 {p.relative_to(ROOT)}")

    def test_repo_skill_ast_matches_manifest_no_extra_unmanifested(self) -> None:
        """防止「写了 @skill 却未进 manifest」漂移（全集以 manifest 为准时，代码侧不得多出名）。"""
        manifest_names = _manifest_skill_names()
        code_names = _discovered_skill_funcs_from_repo()
        extra = code_names - manifest_names
        self.assertFalse(
            extra,
            msg=f"以下函数带 @skill 但未出现在 manifest，请补 manifests/skills.json 或删装饰器: {sorted(extra)}",
        )

    def test_manifest_every_key_has_decorated_impl(self) -> None:
        """manifest 中的每个名字必须在某 skill 源文件中存在同名 @skill 函数。"""
        manifest_names = _manifest_skill_names()
        code_by_name: dict[str, str] = {}
        for path in sorted(SKILLS_DIR.glob("*.py")):
            if path.name.startswith("_"):
                continue
            for n in _ast_skill_defs_in_file(path):
                code_by_name[n] = path.name
        missing = sorted(manifest_names - set(code_by_name.keys()))
        self.assertFalse(
            missing,
            msg=f"manifest 中有名但源码中无 @skill 顶层函数: {missing}",
        )

    def test_gen_oi_tool_map_script_check_mode(self) -> None:
        script = ROOT / "scripts" / "gen_oi_tool_map.py"
        self.assertTrue(script.is_file(), msg="缺少 scripts/gen_oi_tool_map.py")
        proc = subprocess.run(
            [sys.executable, str(script), "--check"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            proc.returncode,
            0,
            msg=(proc.stdout or "") + (proc.stderr or ""),
        )


if __name__ == "__main__":
    unittest.main()
