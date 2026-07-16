"""Compatibility exports for the registry-backed Agent skill runtime."""

from app.services.agent.capabilities import (
    SkillCapability,
    select_skills,
    skill_prompt,
)

__all__ = ["SkillCapability", "select_skills", "skill_prompt"]
