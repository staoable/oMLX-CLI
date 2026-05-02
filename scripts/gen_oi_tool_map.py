#!/usr/bin/env python3
"""根据 `manifests/skills.json` + 源码 AST 生成 `OI_TOOL_MAP.json` 中的 `skills` 列表。

用法：
  python3 scripts/gen_oi_tool_map.py --write   # 写回仓库根 OI_TOOL_MAP.json
  python3 scripts/gen_oi_tool_map.py --check  # 仅校验当前文件与生成结果一致（CI）

权威清单以 manifest 的 `skills` 键为准；`source_file` 由扫描 `.omlxcli/skills/*.py` 中带 @skill 的顶层函数推断。

流程与约定见仓库根目录 **`Skills_README.md`**。
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = ROOT / ".omlxcli" / "skills"
MANIFEST_PATH = SKILLS_DIR / "manifests" / "skills.json"
OUT_PATH = ROOT / "OI_TOOL_MAP.json"

RUNTIME_PROTOCOL = {
    "description": "非 skill 项：会话引擎协议与执行面，仍记在映射中便于文档交叉引用",
    "run_shell": {
        "web_status": "implemented",
        "evidence": ["webapi/session_engine.py", "webapi/execution_policy.py"],
    },
    "run_skill": {
        "web_status": "implemented",
        "evidence": ["webapi/skill_runner.py", ".omlxcli/skills/_registry.py"],
    },
    "final_answer_protocol": {
        "web_status": "implemented",
        "evidence": ["webapi/engine_protocol.py"],
    },
}


def _ast_skill_defs(path: Path) -> set[str]:
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


def discover_skill_sources() -> dict[str, str]:
    """skill 函数名 -> 所在文件名。"""
    mapping: dict[str, str] = {}
    for path in sorted(SKILLS_DIR.glob("*.py")):
        if path.name.startswith("_"):
            continue
        for fn in _ast_skill_defs(path):
            if fn in mapping:
                raise SystemExit(
                    f"重复的技能名 {fn!r}：同时出现在 {mapping[fn]} 与 {path.name}"
                )
            mapping[fn] = path.name
    return mapping


def load_manifest_names() -> list[str]:
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    skills = data.get("skills")
    if not isinstance(skills, dict):
        raise SystemExit("manifest.skills 必须是对象")
    return sorted(skills.keys())


def build_payload() -> dict:
    manifest_names = load_manifest_names()
    sources = discover_skill_sources()
    missing = [n for n in manifest_names if n not in sources]
    if missing:
        raise SystemExit(
            "manifest 中有以下技能名在源码中无 @skill 顶层实现: " + ", ".join(missing)
        )
    skills = [
        {
            "name": name,
            "source_file": sources[name],
            "web_status": "implemented",
            "invoke": "run_skill",
        }
        for name in manifest_names
    ]
    return {
        "version": 2,
        "scope": "omlxcli_skills_only",
        "description": (
            "本仓库技能全集 = `.omlxcli/skills`；权威清单以 `manifests/skills.json` 的 `skills` 键为准。"
            " `skills` 数组由 `scripts/gen_oi_tool_map.py` 生成，请勿手改该数组（改 manifest 后运行 --write）。"
        ),
        "manifest_path": ".omlxcli/skills/manifests/skills.json",
        "skills": skills,
        "runtime_protocol": RUNTIME_PROTOCOL,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--write",
        action="store_true",
        help="写回 OI_TOOL_MAP.json",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="校验磁盘上 OI_TOOL_MAP.json 与生成结果一致",
    )
    args = parser.parse_args()
    if args.write == args.check:
        parser.error("请指定其一：--write 或 --check")

    built = build_payload()
    if args.write:
        OUT_PATH.write_text(
            json.dumps(built, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Wrote {OUT_PATH.relative_to(ROOT)}", file=sys.stderr)
        return

    if not OUT_PATH.is_file():
        raise SystemExit(f"缺少 {OUT_PATH}")
    on_disk = json.loads(OUT_PATH.read_text(encoding="utf-8"))
    if on_disk.get("skills") != built["skills"]:
        raise SystemExit(
            "OI_TOOL_MAP.json 的 skills 与生成结果不一致，请运行：\n"
            "  python3 scripts/gen_oi_tool_map.py --write"
        )
    # description / 其它键允许人工微调；skills 必须一致
    print("OK: skills[] matches manifest + AST", file=sys.stderr)


if __name__ == "__main__":
    main()
