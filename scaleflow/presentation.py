"""Plain-language views of existing process records; no scenario-specific findings."""
from .engine import STAGES, dt

STEP_NAMES = dict(zip(STAGES, ['Request', 'Collection', 'Transport & receipt', 'Laboratory processing', 'Medical review', 'Report preparation']))
CATEGORY_NAMES = {'pending_lab_slot': 'waiting for a laboratory slot', 'courier_suspension': 'courier suspension',
                  'appointment_change': 'collection appointment change', 'receipt_check': 'sample receipt clarification'}
JOURNEY_GROUPS = [('Request', STAGES[:1]), ('Collection', STAGES[1:2]), ('Transport', STAGES[2:3]),
                  ('Laboratory', STAGES[3:4]), ('Review & report', STAGES[4:])]

def date_text(value):
    return dt(value).strftime('%d %b %Y, %H:%M') if value else '—'

def duration_text(hours):
    return f'{hours:.1f} hours' if hours < 24 else f'{hours/24:.1f} days'

def journey_counts(summary):
    return [{'name': name, 'waiting': sum(summary['stages'].get(s, {}).get('active', 0) for s in stages),
             'overdue': sum(summary['stages'].get(s, {}).get('overdue', 0) for s in stages)} for name, stages in JOURNEY_GROUPS]

def status_text(row):
    if row['operational_status'] == 'interrupted':
        return 'Interrupted & overdue' if row['overdue'] else 'Interrupted'
    return 'Overdue' if row['overdue'] else row['operational_status'].title()

def filter_attention(rows, stage='All stages', partner='All locations', status='All statuses', search=''):
    return [r for r in rows if (stage=='All stages' or r['current_stage']==stage)
            and (partner=='All locations' or r['partner_location']==partner)
            and (status=='All statuses' or status=='Overdue' and r['overdue']
                 or status=='Interrupted' and r['operational_status']=='interrupted'
                 or status=='Interrupted & overdue' and r['operational_status']=='interrupted' and r['overdue'])
            and search.strip().lower() in r['case_id'].lower()]

def selected_case(rows, selection):
    indices = selection.get('rows', [])
    return rows[indices[0]] if indices and 0 <= indices[0] < len(rows) else None

def history_rows(history, cutoff):
    entries = {e['stage']: e['timestamp'] for e in history['events'] if e['event_type']=='entered'}
    completions = {e['stage']: e['timestamp'] for e in history['events'] if e['event_type']=='completed'}
    result = []
    for stage in STAGES:
        if stage not in entries:
            continue
        completed = completions.get(stage)
        hours = (dt(completed or cutoff)-dt(entries[stage])).total_seconds()/3600
        result.append({'Process step': STEP_NAMES[stage], 'Date entered': date_text(entries[stage]),
                       'Date completed': date_text(completed), 'Time spent or waiting': duration_text(hours)+(' waiting' if not completed else '')})
    return result
