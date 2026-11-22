from .catalog import store_new_task
from .layout import validate_layout
from .protocols import make_protocol


def open_task(db, name, unit, threshold, max_change, segments):
    protocol = make_protocol(name, unit, threshold, max_change)
    layouts = validate_layout(segments)
    return store_new_task(db, protocol, layouts)
