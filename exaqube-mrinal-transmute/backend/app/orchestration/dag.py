"""DAG validation and execution boundary (execution not implemented yet)."""

from app.models.documents import WorkflowDefinition


def validate_dag(workflow: WorkflowDefinition) -> None:
    node_ids = {node.id for node in workflow.nodes}
    if len(node_ids) != len(workflow.nodes):
        raise ValueError("Workflow node IDs must be unique.")
    for edge in workflow.edges:
        if edge.source not in node_ids or edge.target not in node_ids:
            raise ValueError("Workflow edges must reference existing nodes.")


async def execute_workflow(_: WorkflowDefinition) -> None:
    raise NotImplementedError("Workflow execution is planned for a later milestone.")

