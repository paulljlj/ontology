"""Time-bounded allowlisted observations for satellite diagnosis."""
from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta
from pathlib import Path

TABLES = ('cases', 'nodes', 'links', 'services', 'routes', 'route_hops',
          'traffic', 'node_metrics', 'link_metrics', 'service_metrics', 'events')


def instant(value: str) -> datetime:
    return datetime.fromisoformat(value)


def load_allowlist(root: str | Path) -> tuple[Path, set[str]]:
    base = Path(root).resolve()
    manifest = json.loads((base / 'manifest.json').read_text(encoding='utf-8-sig'))
    allowed = set(manifest['diagnosis_allowlist'])
    # A manifest cannot be used to grant access to evaluation or other locations.
    for name in allowed:
        normalized = name.replace('\\', '/')
        p = Path(normalized)
        if (name != normalized or p.is_absolute() or '..' in p.parts
                or normalized.startswith('evaluation/') or normalized == 'evaluation'):
            raise ValueError('unsafe diagnosis allowlist')
        target = (base / p).resolve()
        if target != base / p:
            raise ValueError('diagnosis allowlist must not follow symlinks')
        if target.is_relative_to(base / 'evaluation'):
            raise ValueError('evaluation cannot be a diagnosis input')
    return base, allowed


def read_table(root: str | Path, name: str, case_id: str | None = None) -> list[dict]:
    if name not in TABLES:
        raise ValueError('unknown observation table')
    base, allow = load_allowlist(root)
    path = 'observed/' + name + '.csv'
    if path not in allow:
        raise ValueError('observation is not in diagnosis_allowlist: ' + path)
    with (base / path).open(encoding='utf-8-sig', newline='') as stream:
        return [row for row in csv.DictReader(stream)
                if case_id is None or not row.get('case_id') or row['case_id'] == case_id]


def load_case(root: str | Path, case_id: str, cutoff: str | None = None,
              observation_at: str | None = None) -> dict:
    cases = [r for r in read_table(root, 'cases') if r['case_id'] == case_id]
    if len(cases) != 1:
        raise ValueError('unknown case_id: ' + case_id)
    config = cases[0]
    end = instant(config['initial_diagnosis_cutoff'])
    if cutoff is not None:
        end = instant(cutoff)
        if end > instant(config['sample_end_exclusive']) or end < instant(config['baseline_start']):
            raise ValueError('cutoff outside case observation window')
    if end <= instant(config['analysis_start']):
        raise ValueError('cutoff must be later than analysis_start')
    observation_limit = instant(observation_at) if observation_at else None
    if observation_limit and not (instant(config['sample_start']) <= observation_limit < instant(config['sample_end_exclusive'])):
        raise ValueError('observation_at outside case observation window')
    rules_base, allowed = load_allowlist(root)
    if 'demo_rules.json' not in allowed:
        raise ValueError('demo_rules.json not in allowlist')
    rules = json.loads((rules_base / 'demo_rules.json').read_text(encoding='utf-8-sig'))
    sample_length = timedelta(seconds=int(config['sampling_seconds']))
    tables = {}
    for name in TABLES:
        if name == 'cases':
            continue
        rows = read_table(root, name, case_id)
        retained = []
        for row in rows:
            if row.get('available_at') and instant(row['available_at']) > end:
                continue
            if observation_limit and row.get('timestamp') and instant(row['timestamp']) > observation_limit:
                continue
            if observation_limit and name == 'routes' and row.get('effective_from') and instant(row['effective_from']) > observation_limit:
                continue
            if observation_limit and name == 'events' and row.get('event_start') and instant(row['event_start']) > observation_limit:
                continue
            if row.get('timestamp') and instant(row['timestamp']) + sample_length > end:
                continue
            if name == 'routes' and row.get('effective_from') and instant(row['effective_from']) > end:
                continue
            if name == 'events' and row.get('event_start') and instant(row['event_start']) > end:
                continue
            # A closing timestamp cannot leak from a future state update.
            if name == 'events' and row.get('event_end_exclusive') and instant(row['event_end_exclusive']) > end:
                row = dict(row)
                row['event_end_exclusive'] = ''
            retained.append(row)
        tables[name] = retained
    return {'case': config, 'cutoff': end, 'rules': rules, 'tables': tables}


def active_route(graph_rows: dict, service_id: str, when: datetime) -> str | None:
    matches = [r for r in graph_rows['routes'] if r['service_id'] == service_id
               and instant(r['effective_from']) <= when
               and (not r['effective_to_exclusive'] or when < instant(r['effective_to_exclusive']))
               and (not r.get('available_at') or instant(r['available_at']) <= when)]
    if len(matches) > 1:
        raise ValueError('overlapping route versions for ' + service_id)
    return matches[0]['route_id'] if matches else None
