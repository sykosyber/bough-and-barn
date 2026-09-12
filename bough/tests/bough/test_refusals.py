from __future__ import annotations

from osahr import BoundaryState, Expr, Hypergraph, Model, PatternGraph, PatternVertex, Rule, Schema, TemplateGraph, TemplateVertex, VertexType, AttributeSpec, ValueKind

from bough.errors import BoughRefusal
from bough.kinds import EventKind, EventSpec, require_chance_has_hazard
from bough.spec import compile_model


def _flip_rule(hazard: str) -> Rule:
    return Rule(
        "flip-on",
        PatternGraph((PatternVertex("s", "Site", {"on": False}),)),
        TemplateGraph((TemplateVertex("s", "Site", {"on": True}),)),
        Expr(hazard),
    )


def _empty_model(rules, memory=None):
    schema = Schema(
        [VertexType("Site", {"on": AttributeSpec(ValueKind.BOOL, required=True)})],
        [],
        schema_id="refuse",
    )
    graph = Hypergraph(schema, namespace=1)
    graph.add_vertex("Site", {"on": False})
    return Model(graph, BoundaryState({}), rules, {}, memory or {}, model_id="refuse")


def test_non_empty_z_refuses() -> None:
    rule = _flip_rule("1.0")
    model = _empty_model((rule,), memory={"trace": 1})
    try:
        compile_model(model, (EventSpec("flip-on", EventKind.CHANCE, rule),))
    except BoughRefusal as exc:
        assert exc.reason == "NON_EMPTY_Z"
    else:
        raise AssertionError("expected NON_EMPTY_Z")


def test_time_varying_hazard_refuses() -> None:
    rule = Rule(
        "tick",
        PatternGraph((PatternVertex("s", "Site", {"on": False}),)),
        TemplateGraph((TemplateVertex("s", "Site", {"on": True}),)),
        Expr("time"),
        hazard_upper_bound=Expr("1.0"),
    )
    model = _empty_model((rule,))
    try:
        compile_model(model, (EventSpec("tick", EventKind.CHANCE, rule),))
    except BoughRefusal as exc:
        assert exc.reason == "TIME_VARYING_HAZARD"
    else:
        raise AssertionError("expected TIME_VARYING_HAZARD")


def test_decision_with_hazard_refuses() -> None:
    rule = _flip_rule("1.0")
    model = _empty_model((rule,))
    try:
        compile_model(model, (EventSpec("flip-on", EventKind.DECISION, rule),))
    except BoughRefusal as exc:
        assert exc.reason == "DECISION_WITH_HAZARD"
    else:
        raise AssertionError("expected DECISION_WITH_HAZARD")


def test_chance_without_hazard_refuses() -> None:
    try:
        require_chance_has_hazard("flip-on", None)
    except BoughRefusal as exc:
        assert exc.reason == "CHANCE_WITHOUT_HAZARD"
    else:
        raise AssertionError("expected CHANCE_WITHOUT_HAZARD")
