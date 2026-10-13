"""Explicit generation only. Existing data are reused unless --force is supplied."""
import argparse
import csv
import hashlib
import json
import random
from datetime import timedelta
from pathlib import Path
from scaleflow.engine import dt, snapshot, validate

ROOT = Path(__file__).resolve().parent

def build(config, name, spec):
    rng = random.Random(config['seed'])
    start, cutoff = dt(config['start']), dt(config['cutoff'])
    stages = config['stages']
    requests = sorted(start + timedelta(days=week*7+rng.randrange(7), hours=rng.randrange(8,17), minutes=rng.randrange(60))
                      for week, count in enumerate(spec['weekly_requests']) for _ in range(count))
    cases, histories, jobs = [], {}, []
    for i, request in enumerate(requests, 1):
        case_id = f'VF-{name.upper()}-{i:04}'
        route = rng.choice(['North Clinic', 'Central Clinic', 'West Clinic'])
        case = dict(case_id=case_id, request_date=request.isoformat(), expected_delivery_date=(request+timedelta(days=10)).isoformat(),
                    partner_location=route, laboratory='VitaLab Hub', pathway='Preventive blood panel')
        cases.append(case)
        history = []
        histories[case_id] = history
        def add(stage, kind, timestamp, **extras):
            history.append(dict(case_id=case_id, stage=stage, event_type=kind, timestamp=timestamp.isoformat(), **extras))
        t = request
        add(stages[0], 'entered', t)
        t += timedelta(hours=rng.uniform(1, 9))
        add(stages[0], 'completed', t)
        add(stages[1], 'entered', t)
        scheduling = rng.triangular(18, 100, 38)
        if rng.random() < .07:
            add(stages[1], 'note', t+timedelta(hours=2), category='appointment_change', note='Clinic recorded a collection appointment change; replacement slot confirmed.')
            scheduling += rng.uniform(24, 64)
        t += timedelta(hours=scheduling)
        add(stages[1], 'completed', t)
        add(stages[2], 'entered', t)
        transit = rng.uniform(5, 22)
        if rng.random() < .05:
            add(stages[2], 'note', t+timedelta(hours=1), category='receipt_check', note='Specimen manifest reference required clarification before receipt acceptance.')
            transit += rng.uniform(10, 30)
        receipt = t+timedelta(hours=transit)
        if name == 'disruption':
            outage_start, outage_end = dt(spec['outage_start']), dt(spec['outage_end'])
            if route == spec['affected_route'] and t < outage_end and receipt >= outage_start:
                add(stages[2], 'note', max(t, outage_start)+timedelta(minutes=30), category='courier_suspension',
                    incident_id=spec['incident_id'], status='interrupted',
                    note='North route courier collection suspended. Specimen held in validated refrigerated storage; dispatch restart estimated for 14 October 09:00. Receipt time unconfirmed.')
                receipt = max(receipt, outage_end)+timedelta(hours=rng.uniform(5, 18))
        add(stages[2], 'completed', receipt)
        add(stages[3], 'entered', receipt, status='pending')
        # Draw all individual variation before queue scheduling; no outcome labels.
        jobs.append((receipt, case_id, rng.uniform(*spec['lab_service_hours']), rng.uniform(6, 28), rng.uniform(.3, 5), rng.random()))
    available = [start] * spec['lab_slots']
    for receipt, case_id, service, review, publish, note_draw in sorted(jobs):
        history = histories[case_id]
        def add(stage, kind, timestamp, **extras):
            history.append(dict(case_id=case_id, stage=stage, event_type=kind, timestamp=timestamp.isoformat(), **extras))
        slot = min(range(len(available)), key=lambda n: available[n])
        work_start = max(receipt, available[slot])
        # Notes are created when a real queue condition exists; deliberately incomplete coverage.
        if (work_start-receipt).total_seconds() > 48*3600 and note_draw < .65:
            add(stages[3], 'note', receipt+timedelta(hours=48), category='pending_lab_slot',
                note='Accession awaiting a processing slot. Current batch positions occupied; no additional shift confirmed.')
        add(stages[3], 'work_started', work_start)
        finish = work_start+timedelta(hours=service)
        available[slot] = finish
        add(stages[3], 'completed', finish)
        add(stages[4], 'entered', finish)
        finish += timedelta(hours=review)
        add(stages[4], 'completed', finish)
        add(stages[5], 'entered', finish)
        finish += timedelta(hours=publish)
        add(stages[5], 'completed', finish)
    events = []
    for history in histories.values():
        for sequence, event in enumerate(history):
            if dt(event['timestamp']) <= cutoff:
                events.append(dict(event, sequence=sequence))
    validate(cases, events, stages, config['cutoff'])
    return cases, events

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    config = json.loads((ROOT/'scenarios.json').read_text())
    data = ROOT/'data'
    if data.exists() and not args.force:
        print('Saved data retained. Use --force only for an intentional regeneration.')
        return
    data.mkdir(exist_ok=True)
    manifest = {'seed': config['seed'], 'reference_cutoff': config['cutoff'], 'files': {}}
    for name, spec in config['scenarios'].items():
        cases, events = build(config, name, spec)
        folder = data/name
        folder.mkdir(exist_ok=True)
        for filename, records in [('cases.json', cases), ('stage_events.json', events), ('snapshot.json', snapshot(cases, events, config['cutoff']))]:
            path = folder/filename
            path.write_text(json.dumps(records, indent=2)+'\n', encoding='utf-8')
            manifest['files'][f'{name}/{filename}'] = hashlib.sha256(path.read_bytes()).hexdigest()
        for filename, records in [('cases.csv', cases), ('stage_events.csv', events)]:
            path = folder/filename
            fields = list(dict.fromkeys(key for record in records for key in record))
            with path.open('w', newline='', encoding='utf-8') as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                writer.writerows(records)
            manifest['files'][f'{name}/{filename}'] = hashlib.sha256(path.read_bytes()).hexdigest()
    (data/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print('Generated three deterministic datasets once.')

if __name__ == '__main__':
    main()

