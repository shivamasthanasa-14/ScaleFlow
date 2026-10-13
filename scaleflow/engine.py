"""One cutoff-aware engine for every dataset; standard library only."""
from datetime import datetime, timedelta
from statistics import median

STAGES = ['Test requested', 'Appointment or sample collection', 'Sample or diagnostic data received',
          'Laboratory processing', 'Medical review', 'Report delivered']
PERIODS = {'Last 7 Days': 7, 'Last 30 Days': 30, 'All Time': None}

def dt(value):
    return datetime.fromisoformat(value)

def snapshot(cases, events, cutoff):
    cutoff = dt(cutoff) if isinstance(cutoff, str) else cutoff
    grouped = {}
    for event in events:
        if dt(event['timestamp']) <= cutoff:
            grouped.setdefault(event['case_id'], []).append(event)
    rows = []
    for case in cases:
        requested = dt(case['request_date'])
        if requested > cutoff:
            continue
        history = sorted(grouped.get(case['case_id'], []), key=lambda e: (e['timestamp'], e['sequence']))
        entered = [e for e in history if e['event_type'] == 'entered']
        if not entered:
            continue
        current = entered[-1]
        delivery = next((dt(e['timestamp']) for e in history if e['stage'] == 'Report delivered' and e['event_type'] == 'completed'), None)
        notes = [e for e in history if e['event_type'] == 'note']
        latest_status = next((e['status'] for e in reversed(history) if e.get('status')), 'pending')
        overdue = delivery is None and dt(case['expected_delivery_date']) < cutoff
        rows.append(dict(case, current_stage=current['stage'], operational_status='completed' if delivery else latest_status,
                         overdue=overdue, actual_delivery_date=delivery.isoformat() if delivery else None,
                         waiting_hours=0 if delivery else (cutoff-dt(current['timestamp'])).total_seconds()/3600,
                         elapsed_hours=((delivery or cutoff)-requested).total_seconds()/3600,
                         notes=notes))
    return rows

def metrics(cases, events, cutoff, days=None):
    cutoff = dt(cutoff) if isinstance(cutoff, str) else cutoff
    rows = snapshot(cases, events, cutoff)
    start = cutoff-timedelta(days=days) if days else datetime.min
    delivered = [r for r in rows if r['actual_delivery_date'] and start < dt(r['actual_delivery_date']) <= cutoff]
    active = [r for r in rows if not r['actual_delivery_date']]
    stages = {}
    for r in active:
        entry = stages.setdefault(r['current_stage'], {'active': 0, 'overdue': 0, 'waiting_hours': []})
        entry['active'] += 1
        entry['overdue'] += int(r['overdue'])
        entry['waiting_hours'].append(r['waiting_hours'])
    return {'cases_in_progress': len(active), 'reports_delivered': len(delivered),
            'median_turnaround_hours': median([r['elapsed_hours'] for r in delivered]) if delivered else None,
            'overdue_cases': sum(r['overdue'] for r in active), 'stages': stages}

def stage_durations(events, case_id, cutoff):
    visible = [e for e in events if e['case_id'] == case_id and dt(e['timestamp']) <= dt(cutoff)]
    entries = {e['stage']: dt(e['timestamp']) for e in visible if e['event_type'] == 'entered'}
    return {e['stage']: (dt(e['timestamp'])-entries[e['stage']]).total_seconds()/3600
            for e in visible if e['event_type'] == 'completed'}

def validate(cases, events, stages=STAGES, cutoff=None, fixed_deadline=False):
    if cutoff is None:
        cutoff = max(e['timestamp'] for e in events)
    ids = {c['case_id'] for c in cases}
    assert len(ids) == len(cases), 'Duplicate case IDs'
    assert all(e['case_id'] in ids for e in events), 'Unknown case reference'
    assert all(dt(e['timestamp']) <= dt(cutoff) for e in events), 'Future recorded event'
    for case in cases:
        assert dt(case['expected_delivery_date']) >= dt(case['request_date']), 'Deadline precedes request'
        if fixed_deadline:
            assert dt(case['expected_delivery_date']) == dt(case['request_date']) + timedelta(days=10)
        history = sorted([e for e in events if e['case_id'] == case['case_id']], key=lambda e: e['sequence'])
        assert history and history[0]['stage'] == stages[0] and history[0]['event_type'] == 'entered'
        assert history[0]['timestamp'] == case['request_date']
        previous = dt(case['request_date'])
        index, opened, completed = 0, False, False
        seen = set()
        for e in history:
            timestamp = dt(e['timestamp'])
            assert timestamp >= previous, 'Nonchronological history'
            previous = timestamp
            assert e['event_type'] in ('entered', 'completed', 'work_started', 'note'), 'Unknown event type'
            assert e['stage'] == stages[index], 'Wrong stage order'
            if e['event_type'] in ('entered', 'completed', 'work_started'):
                key = (e['stage'], e['event_type'])
                assert key not in seen, 'Duplicate event'
                seen.add(key)
            if e['event_type'] == 'entered':
                assert not opened and not completed
                opened = True
            elif e['event_type'] == 'completed':
                assert opened
                opened = False
                if index < len(stages)-1:
                    index += 1
                else:
                    completed = True
            else:
                assert opened and not completed
        assert opened or completed, 'Missing next entry'
    rows = snapshot(cases, events, cutoff)
    for r in rows:
        assert r['waiting_hours'] >= 0 and r['elapsed_hours'] >= 0
        durations = stage_durations(events, r['case_id'], cutoff)
        assert abs(sum(durations.values()) + r['waiting_hours'] - r['elapsed_hours']) < 1e-6
    return len(rows)

def attention(rows, stage=None):
    return sorted([r for r in rows if not r['actual_delivery_date'] and
                   (r['overdue'] or r['operational_status'] == 'interrupted') and
                   (stage is None or r['current_stage'] == stage)], key=lambda r: -r['waiting_hours'])

def trend(cases, events, cutoff, days=None):
    cutoff = dt(cutoff)
    start = cutoff-timedelta(days=days) if days else datetime.min
    buckets = {}
    for row in snapshot(cases, events, cutoff):
        if row['actual_delivery_date'] and start < dt(row['actual_delivery_date']) <= cutoff:
            delivered = dt(row['actual_delivery_date'])
            week = (delivered-timedelta(days=delivered.weekday())).date().isoformat()
            buckets.setdefault(week, []).append(row['elapsed_hours']/24)
    return [{'Week of delivery': week, 'Median days': median(values), 'Reports': len(values)} for week, values in sorted(buckets.items())]
