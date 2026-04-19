"""Directory-style skill registry helpers."""

from __future__ import annotations

from pathlib import Path

from skills.base import BaseSkill, SkillDocument, SkillRegistry, load_directory_skills, parse_skill_document


def build_default_registry() -> SkillRegistry:
    """Register the built-in directory skills under skills/*/SKILL.md."""
    return load_directory_skills(Path(__file__).resolve().parent)


__all__ = [
    "BaseSkill",
    "SkillDocument",
    "SkillRegistry",
    "build_default_registry",
    "load_directory_skills",
    "parse_skill_document",
]
