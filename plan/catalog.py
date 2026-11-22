from dataclasses import dataclass
import json

from database import is_key, require_key, write_transaction
from .layout import SegmentLayout, validate_layout
from .protocols import Protocol, make_protocol
from .rationals import parse_rational, rational_text


@dataclass(frozen=True)
class TaskSnapshot:
    task_id: int
    protocol: Protocol
    segments: tuple[SegmentLayout, SegmentLayout]


def initialize_catalog(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS task_catalog (
            task_id INTEGER PRIMARY KEY,
            protocol_name TEXT NOT NULL,
            unit TEXT NOT NULL,
            threshold TEXT NOT NULL,
            max_change TEXT NOT NULL,
            layout TEXT NOT NULL
        )
    ''')


def _task_fields(protocol, segments):
    layout = [(part.slot, part.origin, part.rig, part.beats) for part in segments]
    return (
        protocol.name, protocol.unit, rational_text(protocol.threshold),
        rational_text(protocol.max_change), json.dumps(layout, separators=(',', ':')),
    )


def store_new_task(db, protocol, segments):
    fields = _task_fields(protocol, segments)
    with write_transaction(db):
        cursor = db.execute('''
            INSERT INTO task_catalog (protocol_name, unit, threshold, max_change, layout)
            VALUES (?, ?, ?, ?, ?)
        ''', fields)
        task_id = cursor.lastrowid
    return task_id


def install_task_snapshot(db, snapshot):
    if not isinstance(snapshot, TaskSnapshot) or not is_key(snapshot.task_id):
        raise ValueError('invalid task snapshot identity')
    if not isinstance(snapshot.protocol, Protocol):
        raise ValueError('invalid task snapshot protocol')
    source = snapshot.protocol
    protocol = make_protocol(source.name, source.unit, source.threshold, source.max_change)
    segments = validate_layout(snapshot.segments)
    checked = TaskSnapshot(snapshot.task_id, protocol, segments)
    with write_transaction(db):
        try:
            stored = get_task(db, checked.task_id)
        except KeyError:
            db.execute('''
                INSERT INTO task_catalog
                    (task_id, protocol_name, unit, threshold, max_change, layout)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (checked.task_id, *_task_fields(protocol, segments)))
        else:
            if stored != checked:
                raise ValueError('task identity already holds a different snapshot')
    return checked.task_id


def get_task(db, task_id):
    require_key(task_id)
    row = db.execute('''
        SELECT protocol_name, unit, threshold, max_change, layout
        FROM task_catalog WHERE task_id = ?
    ''', (task_id,)).fetchone()
    if row is None:
        raise KeyError(task_id)
    name, unit, threshold, max_change, layout = row
    protocol = Protocol(name, unit, parse_rational(threshold), parse_rational(max_change))
    segments = tuple(
        SegmentLayout(slot, origin, rig, tuple(beats))
        for slot, origin, rig, beats in json.loads(layout)
    )
    return TaskSnapshot(task_id, protocol, segments)
