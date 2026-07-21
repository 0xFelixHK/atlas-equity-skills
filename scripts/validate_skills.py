#!/usr/bin/env python3
"""Validate Atlas skill structure and security invariants without dependencies."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
FORBIDDEN = {
    "automatic package installation": re.compile(r"\b(?:pip|uv pip)\s+install\b", re.I),
    "credential configuration example": re.compile(r"EDGAR_IDENTITY|email@example", re.I),
    "unsafe shell download": re.compile(r"\b(?:curl|wget)\b[^\n]*(?:\||>|-o\b)", re.I),
    "stale GF-DMA weight formula": re.compile(r"HealthScore\s*=\s*40S_", re.I),
}


def fail(errors: list[str], path: Path, message: str) -> None:
    errors.append(f"{path.relative_to(ROOT)}: {message}")


def parse_frontmatter(path: Path, errors: list[str]) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        fail(errors, path, "missing opening YAML delimiter")
        return {}
    try:
        end = lines.index("---", 1)
    except ValueError:
        fail(errors, path, "missing closing YAML delimiter")
        return {}

    fields: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip():
            continue
        if ":" not in line:
            fail(errors, path, f"invalid frontmatter line: {line!r}")
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip()

    if set(fields) != {"name", "description"}:
        fail(errors, path, "frontmatter must contain only name and description")
    if not fields.get("description"):
        fail(errors, path, "description is empty")
    return fields


def validate_agent_yaml(path: Path, skill_name: str, errors: list[str]) -> None:
    if not path.is_file():
        fail(errors, path, "missing agents/openai.yaml")
        return
    text = path.read_text(encoding="utf-8")
    for key in ("display_name", "short_description", "default_prompt"):
        if not re.search(rf'^  {key}: "[^"\n]+"$', text, re.M):
            fail(errors, path, f"missing or unquoted interface.{key}")
    if f"${skill_name}" not in text:
        fail(errors, path, "default_prompt must mention the skill explicitly")


def validate_skill(directory: Path, errors: list[str]) -> None:
    skill_md = directory / "SKILL.md"
    if not skill_md.is_file():
        fail(errors, skill_md, "missing SKILL.md")
        return

    fields = parse_frontmatter(skill_md, errors)
    name = fields.get("name", "")
    if name != directory.name:
        fail(errors, skill_md, "frontmatter name must match directory name")
    if not NAME_RE.fullmatch(name) or len(name) > 64:
        fail(errors, skill_md, "invalid skill name")

    text = skill_md.read_text(encoding="utf-8")
    if len(text.splitlines()) >= 500:
        fail(errors, skill_md, "SKILL.md must stay below 500 lines")
    if "## Security And Data Handling" not in text:
        fail(errors, skill_md, "missing security and data-handling section")
    if "references/framework.md" not in text:
        fail(errors, skill_md, "missing explicit framework reference routing")

    framework = directory / "references" / "framework.md"
    if not framework.is_file():
        fail(errors, framework, "missing detailed framework reference")
    else:
        ref_text = framework.read_text(encoding="utf-8")
        if "../SKILL.md" not in ref_text or "take precedence" not in ref_text:
            fail(errors, framework, "reference must defer to SKILL.md safety rules")

    validate_agent_yaml(directory / "agents" / "openai.yaml", name, errors)


def validate_workflows(errors: list[str]) -> None:
    workflow_dir = ROOT / ".github" / "workflows"
    for path in sorted(workflow_dir.glob("*.y*ml")):
        text = path.read_text(encoding="utf-8")
        for action in re.findall(r"^\s*uses:\s*([^\s#]+)", text, re.M):
            if action.startswith("./") or action.startswith("docker://"):
                continue
            if not re.fullmatch(r"[^@\s]+@[0-9a-f]{40}", action):
                fail(errors, path, f"third-party action is not pinned to a full commit SHA: {action}")
        if not re.search(r"^permissions:\s*\n\s+contents:\s*read\s*$", text, re.M):
            fail(errors, path, "workflow must default to read-only contents permission")


def main() -> int:
    errors: list[str] = []
    skill_dirs = sorted(path for path in SKILLS.iterdir() if path.is_dir())
    if not skill_dirs:
        errors.append("skills: no skill directories found")
    for directory in skill_dirs:
        validate_skill(directory, errors)
    validate_workflows(errors)

    repository_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in ROOT.rglob("*")
        if path.is_file()
        and ".git" not in path.parts
        and "work" not in path.parts
        and "outputs" not in path.parts
        and path.suffix in {".md", ".yaml", ".yml"}
    )
    for label, pattern in FORBIDDEN.items():
        if pattern.search(repository_text):
            errors.append(f"repository: forbidden pattern found ({label})")

    if errors:
        print("Atlas skill validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print(f"Validated {len(skill_dirs)} Atlas skills successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
