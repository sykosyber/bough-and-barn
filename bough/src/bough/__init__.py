"""Bough: staged-tree compiler over the OSAHR 0.2 kernel."""

from __future__ import annotations

__version__ = "0.2.0"

from bough.compare import KERNEL_SCHEDULERS, SchedulerAgreement, agree_first_passage
from bough.cypher import automaton_to_cypher
from bough.errors import BoughError, BoughRefusal
from bough.expand import expand
from bough.incrementality import refresh_probabilities, structural_rule_hits
from bough.infer import path_probability, reach
from bough.ir import Horizon, MarkovAutomaton
from bough.kinds import EventKind, EventSpec
from bough.policy import Policy, optimal_policy
from bough.report import CompilationReport, report
from bough.spec import BoughModel, compile_model
from bough.signature import situation_signature
from bough.staging import StagingMode, stage

__all__ = [
    "BoughError",
    "BoughModel",
    "BoughRefusal",
    "CompilationReport",
    "EventKind",
    "EventSpec",
    "Horizon",
    "KERNEL_SCHEDULERS",
    "MarkovAutomaton",
    "Policy",
    "SchedulerAgreement",
    "agree_first_passage",
    "StagingMode",
    "automaton_to_cypher",
    "compile_model",
    "expand",
    "optimal_policy",
    "path_probability",
    "reach",
    "refresh_probabilities",
    "report",
    "situation_signature",
    "stage",
    "structural_rule_hits",
]
