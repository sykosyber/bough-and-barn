"""Anchored canonicalization of (G, B, hash(R))."""

from __future__ import annotations

import hashlib
from typing import Any

from osahr.boundary import BoundaryState
from osahr.canonical import canonical_json, canonicalize
from osahr.graph import Hypergraph
from osahr.ids import EntityId

from bough.errors import BoughRefusal

CANON_NAMESPACE = 0xB0A7


def _digest(payload: Any) -> str:
    return hashlib.blake2b(canonical_json(payload).encode("utf-8"), digest_size=32).hexdigest()


def _initial_colour(graph: Hypergraph, entity_id: EntityId, anchored: frozenset[EntityId]) -> Any:
    if entity_id in anchored:
        return ("A", str(entity_id))
    if entity_id in graph.vertices:
        vertex = graph.vertices[entity_id]
        return ("V", vertex.type_id, canonicalize(vertex.attributes))
    edge = graph.edges[entity_id]
    return ("E", edge.type_id, canonicalize(edge.attributes))


def _neighbour_tokens(
    graph: Hypergraph,
    entity_id: EntityId,
    colour: dict[EntityId, Any],
) -> tuple[Any, ...]:
    tokens: list[Any] = []
    if entity_id in graph.vertices:
        for incidence in graph.incidences_by_vertex.get(entity_id, ()):
            tokens.append(
                (
                    incidence.side.value,
                    incidence.role,
                    incidence.ordinal,
                    colour[incidence.edge_id],
                )
            )
    else:
        edge = graph.edges[entity_id]
        for incidence in edge.incidences:
            tokens.append(
                (
                    incidence.side.value,
                    incidence.role,
                    incidence.ordinal,
                    colour[incidence.vertex_id],
                )
            )
    return tuple(sorted(tokens, key=lambda item: canonical_json(item)))


def _partition(colour: dict[EntityId, Any], derived: list[EntityId]) -> tuple[tuple[str, ...], ...]:
    buckets: dict[Any, list[EntityId]] = {}
    for entity_id in derived:
        buckets.setdefault(colour[entity_id], []).append(entity_id)
    return tuple(
        tuple(sorted(str(entity_id) for entity_id in members))
        for _, members in sorted(buckets.items(), key=lambda item: canonical_json(item[0]))
    )


def _refine(graph: Hypergraph, anchored: frozenset[EntityId]) -> dict[EntityId, Any]:
    entities = list(graph.vertices) + list(graph.edges)
    derived = [entity_id for entity_id in entities if entity_id not in anchored]
    colour = {entity_id: _initial_colour(graph, entity_id, anchored) for entity_id in entities}
    previous: tuple[tuple[str, ...], ...] | None = None
    while True:
        nxt: dict[EntityId, Any] = {}
        for entity_id in entities:
            if entity_id in anchored:
                nxt[entity_id] = ("A", str(entity_id))
            else:
                nxt[entity_id] = _digest((colour[entity_id], _neighbour_tokens(graph, entity_id, colour)))
        classes = _partition(nxt, derived)
        if classes == previous:
            return nxt
        previous = classes
        colour = nxt


def derived_mapping(
    graph: Hypergraph, anchored: frozenset[EntityId]
) -> dict[EntityId, EntityId]:
    colour = _refine(graph, anchored)
    derived = [entity_id for entity_id in list(graph.vertices) + list(graph.edges) if entity_id not in anchored]
    buckets: dict[Any, list[EntityId]] = {}
    for entity_id in derived:
        buckets.setdefault(colour[entity_id], []).append(entity_id)
    for label, members in buckets.items():
        if len(members) > 1:
            raise BoughRefusal(
                "RESIDUAL_SYMMETRY",
                f"derived colour class {label!r} has {len(members)} entities; v0 refuses orbit fallback",
            )
    ordered = sorted(derived, key=lambda entity_id: (colour[entity_id], str(entity_id)))
    return {entity_id: EntityId(CANON_NAMESPACE, index) for index, entity_id in enumerate(ordered)}


def _map_id(entity_id: EntityId, mapping: dict[EntityId, EntityId], anchored: frozenset[EntityId]) -> str:
    if entity_id in anchored:
        return str(entity_id)
    return str(mapping[entity_id])


def serialize_graph(
    graph: Hypergraph,
    boundary: BoundaryState,
    repertoire_hash: str,
    anchored: frozenset[EntityId],
) -> dict[str, Any]:
    mapping = derived_mapping(graph, anchored)
    vertices = []
    for vertex in graph.vertices.values():
        vertices.append(
            {
                "id": _map_id(vertex.entity_id, mapping, anchored),
                "type": vertex.type_id,
                "attributes": canonicalize(vertex.attributes),
            }
        )
    vertices.sort(key=lambda row: row["id"])
    edges = []
    for edge in graph.edges.values():
        edges.append(
            {
                "id": _map_id(edge.entity_id, mapping, anchored),
                "type": edge.type_id,
                "tail": [
                    {
                        "role": incidence.role,
                        "ordinal": incidence.ordinal,
                        "vertex": _map_id(incidence.vertex_id, mapping, anchored),
                    }
                    for incidence in sorted(edge.tail)
                ],
                "head": [
                    {
                        "role": incidence.role,
                        "ordinal": incidence.ordinal,
                        "vertex": _map_id(incidence.vertex_id, mapping, anchored),
                    }
                    for incidence in sorted(edge.head)
                ],
                "attributes": canonicalize(edge.attributes),
            }
        )
    edges.sort(key=lambda row: row["id"])
    handles = []
    for handle_id, handle in sorted(boundary.handles.items()):
        binding = handle.binding
        handles.append(
            {
                "id": handle_id,
                "binding": None
                if binding is None
                else _map_id(binding, mapping, anchored),
                "direction": handle.direction.value,
                "interface_type": handle.interface_type,
            }
        )
    return {
        "vertices": vertices,
        "edges": edges,
        "boundary": handles,
        "repertoire": repertoire_hash,
    }


def situation_signature(
    graph: Hypergraph,
    boundary: BoundaryState,
    repertoire_hash: str,
    anchored: frozenset[EntityId],
) -> str:
    return _digest(serialize_graph(graph, boundary, repertoire_hash, anchored))
