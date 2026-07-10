"""
Relationship / join-path resolver.

Given the flat list of edges from domain_relationships (each edge:
from_dmo --from_field--> to_dmo.to_field), and a list of domain objects the
user selected in the query builder UI, this finds the shortest chain of
joins that connects them all — the same "Customer -> Order -> OrderItem ->
Product -> Supplier" shortest-path behaviour described in the design.

Pure BFS over an in-memory graph. No ORM, no SQLAlchemy.
"""
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class JoinEdge:
    left_dmo: str
    left_field: str
    right_dmo: str
    right_field: str
    label: str | None = None


class RelationshipResolver:
    def __init__(self, relationships: list[dict]):
        """
        relationships: rows from relationship_repo.list_relationships(), e.g.
            {"from_dmo": "customers", "to_dmo": "orders",
             "from_field": "id", "to_field": "customer_id",
             "cardinality": "OneToMany", "label": "Customer places Orders"}
        """
        self._adjacency: dict[str, list[JoinEdge]] = {}
        for r in relationships:
            edge = JoinEdge(
                left_dmo=r["from_dmo"], left_field=r["from_field"],
                right_dmo=r["to_dmo"], right_field=r["to_field"],
                label=r.get("label"),
            )
            self._adjacency.setdefault(edge.left_dmo, []).append(edge)
            # store the reverse direction too so BFS can traverse either way;
            # left/right on the edge itself still reflect the original
            # from_dmo/to_dmo so the SQL generator joins the right columns.
            self._adjacency.setdefault(edge.right_dmo, []).append(edge)

    def known_objects(self) -> set[str]:
        return set(self._adjacency.keys())

    def _shortest_path_edges(self, start: str, goal: str) -> list[JoinEdge] | None:
        """BFS over dmo names, returns the ordered list of edges to traverse
        from `start` to `goal`, or None if they aren't connected."""
        if start == goal:
            return []
        visited = {start}
        queue: deque[tuple[str, list[JoinEdge]]] = deque([(start, [])])
        while queue:
            node, path = queue.popleft()
            for edge in self._adjacency.get(node, []):
                other = edge.right_dmo if edge.left_dmo == node else edge.left_dmo
                if other in visited:
                    continue
                new_path = path + [edge]
                if other == goal:
                    return new_path
                visited.add(other)
                queue.append((other, new_path))
        return None

    def build_join_plan(self, selected_dmos: list[str]) -> list[JoinEdge]:
        """
        Returns an ordered list of join edges connecting every dmo in
        selected_dmos, starting from selected_dmos[0] as the FROM table.
        Raises ValueError if any object can't be reached from what's already
        included (i.e. no relationship path exists).
        """
        if not selected_dmos:
            return []

        included = {selected_dmos[0]}
        join_plan: list[JoinEdge] = []

        for target in selected_dmos[1:]:
            if target in included:
                continue

            # multi-source BFS: shortest path from ANY already-included node
            best_path: list[JoinEdge] | None = None
            for source in included:
                path = self._shortest_path_edges(source, target)
                if path is not None and (best_path is None or len(path) < len(best_path)):
                    best_path = path

            if best_path is None:
                raise ValueError(
                    f"No relationship path found connecting '{target}' to "
                    f"the already-selected objects {sorted(included)}. "
                    f"Define a relationship in domain_relationships first."
                )

            for edge in best_path:
                other = edge.right_dmo if edge.left_dmo in included else edge.left_dmo
                if other not in included:
                    join_plan.append(edge)
                    included.add(other)

        return join_plan