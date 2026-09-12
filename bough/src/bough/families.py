"""Hand-built families. Chance, decisions, and the ontology fragment. Empty Z, frozen Theta."""

from __future__ import annotations

from dataclasses import dataclass, replace

from osahr import (
    AttributeSpec,
    BoundaryState,
    Expr,
    HyperedgeType,
    Hypergraph,
    Model,
    PatternEdge,
    PatternGraph,
    PatternVertex,
    PortSpec,
    Rule,
    Schema,
    TemplateEdge,
    TemplateGraph,
    TemplateVertex,
    ValueKind,
    Var,
    VertexType,
)

from bough.kinds import EventKind, EventSpec
from bough.spec import BoughModel, compile_model

# Hardcoded projection of OSAHR's routes.ttl. No rdflib in this layer.
SITE_A = "urn:syberlabs:benchmark:A"
SITE_B = "urn:syberlabs:benchmark:B"
SITE_C = "urn:syberlabs:benchmark:C"
ROUTE_AB = "urn:syberlabs:benchmark:AB"
ROUTE_BC = "urn:syberlabs:benchmark:BC"
ROUTE_AC = "urn:syberlabs:benchmark:AC"


def bits_model(n: int) -> BoughModel:
    """n independent irreversible bits. All sites start off."""
    schema = Schema(
        [
            VertexType(
                "Site",
                {"on": AttributeSpec(ValueKind.BOOL, required=True)},
            )
        ],
        [],
        schema_id="bough-sites",
    )
    graph = Hypergraph(schema, namespace=0xB175)
    for _ in range(n):
        graph.add_vertex("Site", {"on": False})
    flip = Rule(
        "flip-on",
        PatternGraph((PatternVertex("s", "Site", {"on": False}),)),
        TemplateGraph((TemplateVertex("s", "Site", {"on": True}),)),
        Expr("1.0"),
    )
    model = Model(graph, BoundaryState({}), (flip,), {}, {}, model_id=f"bits-{n}")
    return compile_model(model, (EventSpec("flip-on", EventKind.CHANCE, flip),))


def token_attach_model() -> BoughModel:
    """Two anchored people; attaching a token creates a derived vertex."""
    schema = Schema(
        [
            VertexType("Person", {}),
            VertexType(
                "Token",
                {"kind": AttributeSpec(ValueKind.STRING, required=True)},
            ),
        ],
        [
            HyperedgeType(
                "Holds",
                {"owner": PortSpec("owner", "Person")},
                {"item": PortSpec("item", "Token")},
                {},
            )
        ],
        schema_id="bough-tokens",
    )
    graph = Hypergraph(schema, namespace=0x704E)
    graph.add_vertex("Person", {})
    graph.add_vertex("Person", {})
    attach = Rule(
        "attach-token",
        PatternGraph((PatternVertex("p", "Person"),)),
        TemplateGraph(
            (
                TemplateVertex("p", "Person"),
                TemplateVertex("tok", "Token", {"kind": "mark"}),
            ),
            (
                TemplateEdge(
                    "holds",
                    "Holds",
                    {"owner": ("p",)},
                    {"item": ("tok",)},
                    {},
                ),
            ),
        ),
        Expr("1.0"),
    )
    model = Model(graph, BoundaryState({}), (attach,), {}, {}, model_id="tokens-2")
    return compile_model(model, (EventSpec("attach-token", EventKind.CHANCE, attach),))


@dataclass(frozen=True, slots=True)
class Route:
    uri: str
    source: str
    target: str
    up: bool
    failure: float
    repair: float


@dataclass(frozen=True, slots=True)
class OntologySnapshot:
    sites: tuple[str, ...]
    routes: tuple[Route, ...]

    @property
    def initial(self) -> tuple[bool, ...]:
        return tuple(route.up for route in self.routes)


def ontology_snapshot() -> OntologySnapshot:
    """Three independent routes from OSAHR's ontology probe fixture."""
    return OntologySnapshot(
        sites=(SITE_A, SITE_B, SITE_C),
        routes=(
            Route(ROUTE_AB, SITE_A, SITE_B, True, 0.2, 0.8),
            Route(ROUTE_AC, SITE_A, SITE_C, True, 0.1, 0.4),
            Route(ROUTE_BC, SITE_B, SITE_C, False, 0.5, 0.5),
        ),
    )


def replicate_ontology(snapshot: OntologySnapshot, copies: int) -> OntologySnapshot:
    if copies < 1:
        raise ValueError("copies must be positive")
    sites: list[str] = []
    routes: list[Route] = []
    for index in range(copies):
        names = {uri: f"{uri}:copy{index}" for uri in snapshot.sites}
        sites.extend(names.values())
        routes.extend(
            replace(
                route,
                uri=f"{route.uri}:copy{index}",
                source=names[route.source],
                target=names[route.target],
            )
            for route in snapshot.routes
        )
    return OntologySnapshot(tuple(sorted(sites)), tuple(sorted(routes, key=lambda route: route.uri)))


def ontology_model(copies: int = 1) -> BoughModel:
    """OSAHR ontology-route-control fragment, without history counters or rdflib.

    Availability is an ``Available`` hyperedge: deleted on fail, recreated on
    repair. Route/Site vertices keep URI identity. Counters are omitted so
    fail→repair can coalesce; they would be order leaks in G.
    """
    snapshot = ontology_snapshot() if copies == 1 else replicate_ontology(ontology_snapshot(), copies)
    state = snapshot.initial
    string = AttributeSpec(ValueKind.STRING, required=True, indexed=True)
    rate = AttributeSpec(ValueKind.FLOAT, required=True, minimum=0)
    schema = Schema(
        [
            VertexType("Site", {"uri": string}),
            VertexType(
                "Route",
                {
                    "uri": string,
                    "source": string,
                    "target": string,
                    "up": AttributeSpec(ValueKind.BOOL, required=True),
                    "failure": rate,
                    "repair": rate,
                },
            ),
        ],
        [
            HyperedgeType(
                "Available",
                {
                    "route": PortSpec("route", "Route"),
                    "source": PortSpec("source", "Site"),
                },
                {"target": PortSpec("target", "Site")},
            )
        ],
        schema_id="ontology-route-control-v1",
    )
    graph = Hypergraph(schema, namespace=0x0710)
    sites = {uri: graph.add_vertex("Site", {"uri": uri}).entity_id for uri in snapshot.sites}
    for route, up in zip(snapshot.routes, state, strict=True):
        vertex = graph.add_vertex(
            "Route",
            {
                "uri": route.uri,
                "source": route.source,
                "target": route.target,
                "up": up,
                "failure": route.failure,
                "repair": route.repair,
            },
        )
        if up:
            graph.add_edge(
                "Available",
                {"route": (vertex.entity_id,), "source": (sites[route.source],)},
                {"target": (sites[route.target],)},
            )
    tail, head = {"route": ("r",), "source": ("s",)}, {"target": ("t",)}
    rules: list[Rule] = []
    events: list[EventSpec] = []
    for action, before, after, hazard in (
        ("fail", True, False, "failure"),
        ("repair", False, True, "repair"),
    ):
        vertices = (
            PatternVertex(
                "r",
                "Route",
                {"up": before, "source": Var("src"), "target": Var("dst"), hazard: Var("rate")},
            ),
            PatternVertex("s", "Site", {"uri": Var("src")}),
            PatternVertex("t", "Site", {"uri": Var("dst")}),
        )
        left = PatternGraph(vertices, (PatternEdge("a", "Available", tail, head),) if before else ())
        right = TemplateGraph(
            (
                TemplateVertex("r", "Route", {"up": after}),
                TemplateVertex("s", "Site"),
                TemplateVertex("t", "Site"),
            ),
            (TemplateEdge("a", "Available", tail, head),) if after else (),
        )
        rule = Rule(action, left, right, Expr("rate"))
        rules.append(rule)
        events.append(EventSpec(action, EventKind.CHANCE, rule))
    model = Model(
        graph,
        BoundaryState({}),
        tuple(rules),
        {},
        {},
        model_id=f"ontology-route-control-v1-x{copies}",
    )
    return compile_model(model, tuple(events))


def machine_model() -> BoughModel:
    """Hand-solvable preemptive MDP. Optimal action is protect (value 1 vs 0.5)."""
    schema = Schema(
        [
            VertexType(
                "Machine",
                {
                    "phase": AttributeSpec(ValueKind.STRING, required=True),
                    "outcome": AttributeSpec(ValueKind.STRING, required=True),
                },
            )
        ],
        [],
        schema_id="bough-machine",
    )
    graph = Hypergraph(schema, namespace=0xD1C1)
    graph.add_vertex("Machine", {"phase": "decide", "outcome": "pending"})
    protect = Rule(
        "protect",
        PatternGraph((PatternVertex("m", "Machine", {"phase": "decide"}),)),
        TemplateGraph((TemplateVertex("m", "Machine", {"phase": "done", "outcome": "succeeded"}),)),
        Expr("0"),
    )
    ignore = Rule(
        "ignore",
        PatternGraph((PatternVertex("m", "Machine", {"phase": "decide"}),)),
        TemplateGraph((TemplateVertex("m", "Machine", {"phase": "exposed", "outcome": "pending"}),)),
        Expr("0"),
    )
    succeed = Rule(
        "succeed",
        PatternGraph((PatternVertex("m", "Machine", {"phase": "exposed"}),)),
        TemplateGraph((TemplateVertex("m", "Machine", {"phase": "done", "outcome": "succeeded"}),)),
        Expr("1.0"),
    )
    fail = Rule(
        "fail",
        PatternGraph((PatternVertex("m", "Machine", {"phase": "exposed"}),)),
        TemplateGraph((TemplateVertex("m", "Machine", {"phase": "done", "outcome": "failed"}),)),
        Expr("1.0"),
    )
    model = Model(
        graph,
        BoundaryState({}),
        (protect, ignore, succeed, fail),
        {},
        {},
        model_id="machine-protect",
    )
    return compile_model(
        model,
        (
            EventSpec("protect", EventKind.DECISION, protect),
            EventSpec("ignore", EventKind.DECISION, ignore),
            EventSpec("succeed", EventKind.CHANCE, succeed),
            EventSpec("fail", EventKind.CHANCE, fail),
        ),
    )


def race_model(rate_a: float = 2.0, rate_b: float = 1.0) -> BoughModel:
    """Two competing irreversible jumps. Exact P(a) = rate_a / (rate_a + rate_b).

    DAG family for C2: non-trivial reach mass, one event to absorption.
    """
    if rate_a <= 0.0 or rate_b <= 0.0:
        raise ValueError("race rates must be positive")
    schema = Schema(
        [
            VertexType(
                "Track",
                {"winner": AttributeSpec(ValueKind.STRING, required=True)},
            )
        ],
        [],
        schema_id="bough-race",
    )
    graph = Hypergraph(schema, namespace=0x2ACE)
    graph.add_vertex("Track", {"winner": "pending"})
    take_a = Rule(
        "take-a",
        PatternGraph((PatternVertex("t", "Track", {"winner": "pending"}),)),
        TemplateGraph((TemplateVertex("t", "Track", {"winner": "a"}),)),
        Expr(repr(float(rate_a))),
    )
    take_b = Rule(
        "take-b",
        PatternGraph((PatternVertex("t", "Track", {"winner": "pending"}),)),
        TemplateGraph((TemplateVertex("t", "Track", {"winner": "b"}),)),
        Expr(repr(float(rate_b))),
    )
    model = Model(
        graph,
        BoundaryState({}),
        (take_a, take_b),
        {},
        {},
        model_id=f"race-{rate_a}-{rate_b}",
    )
    return compile_model(
        model,
        (
            EventSpec("take-a", EventKind.CHANCE, take_a),
            EventSpec("take-b", EventKind.CHANCE, take_b),
        ),
    )


def race_terminal_label(situation) -> str | None:
    winner = next(vertex.attributes["winner"] for vertex in situation.graph.vertices.values())
    return None if winner == "pending" else winner


def bits_all_on_label(n: int):
    def label(situation) -> str | None:
        ons = sum(1 for vertex in situation.graph.vertices.values() if vertex.attributes.get("on"))
        return "all-on" if ons == n else None

    return label


def preempt_model() -> BoughModel:
    """Decision and chance both enabled at the root; chance must be suppressed."""
    schema = Schema(
        [
            VertexType(
                "Cell",
                {"mode": AttributeSpec(ValueKind.STRING, required=True)},
            )
        ],
        [],
        schema_id="bough-preempt",
    )
    graph = Hypergraph(schema, namespace=0x9EE7)
    graph.add_vertex("Cell", {"mode": "open"})
    choose = Rule(
        "choose",
        PatternGraph((PatternVertex("c", "Cell", {"mode": "open"}),)),
        TemplateGraph((TemplateVertex("c", "Cell", {"mode": "chosen"}),)),
        Expr("0"),
    )
    decay = Rule(
        "decay",
        PatternGraph((PatternVertex("c", "Cell", {"mode": "open"}),)),
        TemplateGraph((TemplateVertex("c", "Cell", {"mode": "gone"}),)),
        Expr("1.0"),
    )
    model = Model(graph, BoundaryState({}), (choose, decay), {}, {}, model_id="preempt")
    return compile_model(
        model,
        (
            EventSpec("choose", EventKind.DECISION, choose),
            EventSpec("decay", EventKind.CHANCE, decay),
        ),
    )
