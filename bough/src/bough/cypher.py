"""Neo4j inspection export. Cypher text is the product; the expander does not talk to Neo4j."""

from __future__ import annotations

import os
from typing import Any

from bough.ir import MarkovAutomaton


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def automaton_to_cypher(automaton: MarkovAutomaton) -> str:
    """Deterministic Cypher. Each statement is self-contained (safe to run one-by-one)."""
    lines = [
        "// Bough Markov automaton — inspection only, not an expansion backend.",
        "CREATE CONSTRAINT situation_signature IF NOT EXISTS FOR (s:Situation) REQUIRE s.signature IS UNIQUE;",
    ]
    for signature in sorted(automaton.situations):
        situation = automaton.situations[signature]
        label = "null" if situation.label is None else f"'{_escape(situation.label)}'"
        root = "true" if signature == automaton.root else "false"
        lines.append(
            "MERGE (s:Situation {signature: '" + situation.signature + "'}) "
            "ON CREATE SET "
            f"s.kind = '{situation.kind.value}', "
            f"s.depth = {situation.depth}, "
            f"s.label = {label}, "
            f"s.root = {root};"
        )
    edge_rows = []
    for situation in automaton.situations.values():
        for edge in situation.outgoing:
            edge_rows.append(
                (edge.source, edge.target, edge.rule_id, edge.match_id, edge.kind, edge.probability)
            )
    edge_rows.sort(key=lambda row: (row[0], row[1], row[2], row[3]))
    for source, target, rule_id, match_id, kind, probability in edge_rows:
        prob = "null" if probability is None else repr(float(probability))
        lines.append(
            f"MATCH (a:Situation {{signature: '{source}'}}) "
            f"MATCH (b:Situation {{signature: '{target}'}}) "
            "CREATE (a)-[:JUMP {"
            f"rule_id: '{_escape(rule_id)}', "
            f"match_id: '{_escape(match_id)}', "
            f"kind: '{kind.value}', "
            f"probability: {prob}"
            "}]->(b);"
        )
    return "\n".join(lines) + "\n"


def try_push_cypher(cypher: str, *, uri: str | None = None) -> dict[str, Any]:
    """Optional live push. Missing driver or NEO4J_URI is a no-op, not a refusal."""
    uri = uri or os.environ.get("NEO4J_URI")
    if not uri:
        return {"pushed": False, "reason": "NEO4J_URI unset"}
    try:
        from neo4j import GraphDatabase
    except ImportError:
        return {"pushed": False, "reason": "neo4j driver not installed"}
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "")
    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        with driver.session() as session:
            for statement in cypher.split(";"):
                statement = statement.strip()
                if not statement or statement.startswith("//"):
                    continue
                session.run(statement)
    finally:
        driver.close()
    return {"pushed": True, "uri": uri}
