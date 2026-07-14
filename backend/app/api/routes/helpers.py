def parse_workspace_project_id(project_id: str) -> int | None:
    """Return a database id, or None for the stable prototype workspace."""
    if project_id == "prototype":
        return None
    try:
        return int(project_id)
    except ValueError:
        return None
