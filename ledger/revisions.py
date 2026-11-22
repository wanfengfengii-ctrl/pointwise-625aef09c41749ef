from .query import get_revision


def correction_parent(db, task_id, layout, parent_id):
    if parent_id is None:
        return None
    parent = get_revision(db, parent_id)
    original_scope = (parent.task_id, parent.slot, parent.origin, parent.rig)
    requested_scope = (task_id, layout.slot, layout.origin, layout.rig)
    if original_scope != requested_scope:
        raise ValueError('correction parent belongs to another task segment or rig')
    return parent.revision_id
