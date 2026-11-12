"""Structural validation and stable topological ordering for workflow DAGs."""

from collections import defaultdict, deque

from app.models.documents import WorkflowDefinition


class WorkflowValidationError(ValueError):
    """A workflow definition is not an executable typed DAG."""


def topological_order(workflow: WorkflowDefinition, *, allow_unbound_sources: bool = False) -> list[str]:
    nodes = {node.id: node for node in workflow.nodes}
    if len(nodes) != len(workflow.nodes):
        raise WorkflowValidationError("Workflow node IDs must be unique.")
    if not nodes:
        raise WorkflowValidationError("A workflow must contain at least one node.")

    outgoing: dict[str, list[str]] = defaultdict(list)
    incoming: dict[str, list[str]] = defaultdict(list)
    seen_edges: set[tuple[str, str]] = set()
    for edge in workflow.edges:
        if edge.source not in nodes or edge.target not in nodes:
            raise WorkflowValidationError("Workflow edges must reference existing nodes.")
        pair = (edge.source, edge.target)
        if pair in seen_edges:
            raise WorkflowValidationError("Workflow edges must be unique.")
        if edge.source == edge.target:
            raise WorkflowValidationError("A workflow node cannot depend on itself.")
        seen_edges.add(pair)
        outgoing[edge.source].append(edge.target)
        incoming[edge.target].append(edge.source)

    # Detect cycles before type compatibility so cyclic graphs receive a precise error.
    indegree = {node_id: len(incoming[node_id]) for node_id in nodes}
    ready = deque(node.id for node in workflow.nodes if indegree[node.id] == 0)
    order: list[str] = []
    while ready:
        current = ready.popleft()
        order.append(current)
        for downstream in outgoing[current]:
            indegree[downstream] -= 1
            if indegree[downstream] == 0:
                ready.append(downstream)
    if len(order) != len(nodes):
        raise WorkflowValidationError("Workflow contains a dependency cycle.")

    compatible = {
        "source": {"interpretation", "transformation"},
        "interpretation": {"planning", "transformation"},
        "planning": {"transformation"},
        "transformation": {"output"},
        "output": set(),
    }
    for node in workflow.nodes:
        parents = incoming[node.id]
        if node.kind == "source":
            if parents:
                raise WorkflowValidationError("Source nodes cannot have dependencies.")
            if not node.document_id and not allow_unbound_sources:
                raise WorkflowValidationError("Each source node requires document_id on the node or run request.")
        elif not parents:
            raise WorkflowValidationError(f"Node '{node.id}' is missing its upstream dependency.")

        if node.kind == "interpretation" and (
            len(parents) != 1 or nodes[parents[0]].kind != "source"
        ):
            raise WorkflowValidationError("Interpretation nodes require exactly one source dependency.")
        if node.kind == "planning" and (
            len(parents) != 1 or nodes[parents[0]].kind != "interpretation"
        ):
            raise WorkflowValidationError("Planning nodes require exactly one interpretation dependency.")
        if node.kind == "transformation" and not any(
            nodes[parent].kind in {"source", "interpretation", "planning"} for parent in parents
        ):
            raise WorkflowValidationError("Transformation nodes require source/interpretation dependencies.")
        if node.kind == "output" and (
            len(parents) != 1 or nodes[parents[0]].kind != "transformation"
        ):
            raise WorkflowValidationError("Output nodes require exactly one transformation dependency.")

        for parent_id in parents:
            parent_kind = nodes[parent_id].kind
            if node.kind not in compatible[parent_kind]:
                raise WorkflowValidationError(
                    f"Incompatible workflow connection: {parent_kind} node '{parent_id}' cannot feed {node.kind} node '{node.id}'."
                )

    if not any(node.kind == "output" for node in workflow.nodes):
        raise WorkflowValidationError("A workflow must include at least one output node.")
    _validate_transform_ancestors(nodes, incoming, order)
    return order


def validate_dag(workflow: WorkflowDefinition, *, allow_unbound_sources: bool = False) -> None:
    topological_order(workflow, allow_unbound_sources=allow_unbound_sources)


def _validate_transform_ancestors(nodes, incoming, order) -> None:
    ancestors: dict[str, set[str]] = {}
    for node_id in order:
        inherited: set[str] = set()
        for parent in incoming[node_id]:
            inherited.add(parent)
            inherited.update(ancestors[parent])
        ancestors[node_id] = inherited
        node = nodes[node_id]
        if node.kind != "transformation":
            continue
        upstream_kinds = {nodes[item].kind for item in inherited}
        if "source" not in upstream_kinds or "interpretation" not in upstream_kinds:
            raise WorkflowValidationError(
                f"Transformation node '{node.id}' requires an upstream source and interpretation."
            )
        sources = [nodes[item] for item in inherited if nodes[item].kind == "source"]
        interpretations = [nodes[item] for item in inherited if nodes[item].kind == "interpretation"]
        plans = [nodes[item] for item in inherited if nodes[item].kind == "planning"]
        if len(sources) != 1 or len(interpretations) != 1 or len(plans) > 1:
            raise WorkflowValidationError(
                f"Transformation node '{node.id}' has ambiguous upstream source, interpretation, or plan dependencies."
            )
        if any(plan.target_format != node.target_format for plan in plans):
            raise WorkflowValidationError("An upstream planning node target_format must match its transformation node.")
