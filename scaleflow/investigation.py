"""Read-only evidence tools and clearly labelled deterministic example reports."""
from collections import Counter
from statistics import median
from .engine import STAGES, PERIODS, dt, snapshot, attention, stage_durations

class EvidenceTools:
    def __init__(self, cases, events, cutoff, period):
        if period not in PERIODS:
            raise ValueError('Unknown reporting period')
        self.cases, self.events, self.cutoff, self.period = cases, events, cutoff, period
        self.rows = snapshot(cases, events, cutoff)
        self.by_id = {r['case_id']: r for r in self.rows}

    def get_delayed_cases(self, stage, reporting_period):
        if stage not in STAGES or reporting_period != self.period:
            raise ValueError('Stage or reporting period outside selected context')
        rows = attention(self.rows, stage)
        return {'cutoff': self.cutoff, 'scope': 'All open overdue or interrupted cases at cutoff; period applies to completed-performance comparisons.',
                'count': len(rows), 'cases': [{k: r[k] for k in ('case_id', 'current_stage', 'operational_status', 'overdue',
                                                              'waiting_hours', 'expected_delivery_date', 'partner_location')} for r in rows]}

    def get_case_history(self, case_id):
        if not isinstance(case_id, str) or case_id not in self.by_id:
            raise ValueError('Unknown case at reporting cutoff')
        row = self.by_id[case_id]
        return {'case_id': case_id, 'cutoff': self.cutoff, 'completed_stage_hours': stage_durations(self.events, case_id, self.cutoff),
                'current_stage': row['current_stage'], 'waiting_hours': row['waiting_hours'],
                'events': sorted([e for e in self.events if e['case_id'] == case_id and dt(e['timestamp']) <= dt(self.cutoff)],
                                 key=lambda e: (e['timestamp'], e['sequence']))}

    def get_exception_notes(self, case_ids):
        if not isinstance(case_ids, list) or not case_ids or len(case_ids) > 250 or any(not isinstance(i, str) or i not in self.by_id for i in case_ids):
            raise ValueError('Supply 1–250 known case IDs')
        return [{'case_id': i, 'notes': self.by_id[i]['notes']} for i in dict.fromkeys(case_ids)]

    def dispatch(self, name, arguments):
        if name not in ('get_delayed_cases', 'get_case_history', 'get_exception_notes') or not isinstance(arguments, dict):
            raise ValueError('Unknown tool or malformed arguments')
        try:
            return getattr(self, name)(**arguments)
        except TypeError as exc:
            raise ValueError('Invalid tool arguments') from exc

def baseline_stage(cases, events, cutoff, stage, period):
    from datetime import timedelta
    end = dt(cutoff)
    start = end-timedelta(days=PERIODS[period]) if PERIODS[period] else dt('1900-01-01')
    values = []
    for e in events:
        if e['stage'] == stage and e['event_type'] == 'completed' and start < dt(e['timestamp']) <= end:
            values.append(stage_durations(events, e['case_id'], cutoff)[stage])
    return {'median_hours': median(values) if values else None, 'count': len(values)}

def example_report(tools, stage):
    records = tools.get_delayed_cases(stage, tools.period)
    ids = [r['case_id'] for r in records['cases']]
    if not ids:
        return {'mode': 'Deterministic example investigation', 'what_we_found': ['No open overdue or interrupted cases in this stage at the selected cutoff.'],
                'contributing': [], 'missing': [], 'follow_ups': [], 'trace': [], 'case_ids': []}
    notes = tools.get_exception_notes(ids)
    history = tools.get_case_history(ids[0])
    categories = Counter(n.get('category', 'uncategorized') for r in notes for n in r['notes'] if n['stage'] == stage)
    missing = [r['case_id'] for r in notes if not any(n['stage'] == stage for n in r['notes'])]
    waiting = [r['waiting_hours']/24 for r in records['cases']]
    contributors = []
    followups = []
    # Follow-ups are questions constructed from available evidence, not scenario lookup text.
    for category in categories:
        matching = [(r['case_id'], n) for r in notes for n in r['notes'] if n['stage'] == stage and n.get('category', 'uncategorized') == category]
        case_id, note = matching[0]
        from .presentation import CATEGORY_NAMES
        reason = CATEGORY_NAMES.get(category,category.replace('_',' '))
        contributors.append(f"{len(set(i for i, _ in matching))} cases have notes recording {reason}.")
        followups.append(f"Confirm whether {reason} is still blocking work and when processing can resume.")
    if missing:
        followups.append(f"Request a blocker and completion estimate for the {len(missing)} cases without a recorded reason.")
    from .presentation import STEP_NAMES
    overdue = sum(r['overdue'] for r in records['cases'])
    interrupted = sum(r['operational_status']=='interrupted' for r in records['cases'])
    lead = f"{overdue} overdue {'case is' if overdue==1 else 'cases are'} currently waiting at {STEP_NAMES[stage].lower()}." if overdue else f"{interrupted} interrupted {'case is' if interrupted==1 else 'cases are'} currently waiting at {STEP_NAMES[stage].lower()}."
    observations = [lead, f"Typical waiting time is {median(waiting):.1f} days."]
    if interrupted and overdue:
        observations.append(f"{interrupted} cases are interrupted; some are also overdue.")
    return {'mode': 'Deterministic example investigation',
            'what_we_found': observations,
            'contributing': contributors or ['No stage-specific blocker has been recorded for these cases.'],
            'missing': [f"{len(missing)} cases have no recorded reason for this step; causes remain unknown.", 'Recorded notes do not confirm recovery dates.'] if missing else ['Recorded notes do not confirm recovery dates.'],
            'follow_ups': followups, 'case_ids': ids,
            'evidence_details': {'waiting_range_days': [round(min(waiting),1), round(max(waiting),1)],
                                 'case_ids_without_reason': missing, 'recorded_notes': notes, 'inspected_case': ids[0],
                                 'interrupted_cases': interrupted, 'overdue_cases': overdue},
            'trace': [{'tool': 'get_delayed_cases', 'finding': f'{len(ids)} affected case(s)', 'arguments': {'stage': stage, 'reporting_period': tools.period}},
                      {'tool': 'get_case_history', 'finding': f'{len(history["events"])} visible events for {ids[0]}', 'arguments': {'case_id': ids[0]}},
                      {'tool': 'get_exception_notes', 'finding': f'{sum(len(r["notes"]) for r in notes)} visible notes; {len(missing)} cases without stage-specific notes', 'arguments': {'case_ids': ids}}]}

def report_markdown(report, context):
    lines = ['# ScaleFlow investigation', context, report['mode']]
    for key, heading in [('what_we_found','What we found'), ('contributing','What may be contributing'),
                         ('missing','What information is missing'), ('follow_ups','Suggested operational follow-ups')]:
        lines += ['', '## '+heading]+['- '+str(item) for item in report.get(key, [])]
    lines += ['', '## Tools consulted']+['- '+t['tool']+': '+t['finding'] for t in report.get('trace', [])]
    return '\n'.join(lines)
