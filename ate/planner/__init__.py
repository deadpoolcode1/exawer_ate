"""ate.planner — rule-based test plan generator.

For M1: takes a parsed Document IR and produces a populated test plan
following the structure of references/Feature Name Test Plan Template.xlsx.

M1 is rule-based / template-driven (no AI).
M3 will swap the rule-based per-category step generation for prompt-driven
AI generation; the IR + Plan model boundary stays the same.
"""
from ate.planner.generator import generate_plan, generate_plan_to_xlsx
from ate.planner.model import Plan, PlanRow, Requirement

__all__ = ["generate_plan", "generate_plan_to_xlsx", "Plan", "PlanRow", "Requirement"]
