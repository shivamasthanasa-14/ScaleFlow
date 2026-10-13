import hashlib
import json
from pathlib import Path
from .engine import validate, STAGES

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT/'scenarios.json').read_text())
LABELS = {v['label']: k for k, v in CONFIG['scenarios'].items()}

def load_dataset(label):
    if label not in LABELS:
        raise ValueError('Unknown sample dataset')
    key = LABELS[label]
    folder = ROOT/'data'/key
    cases = json.loads((folder/'cases.json').read_text())
    events = json.loads((folder/'stage_events.json').read_text())
    cutoff = CONFIG['scenarios'][key].get('reference_cutoff', CONFIG['cutoff'])
    validate(cases, events, STAGES, cutoff, fixed_deadline=True)
    return cases, events, cutoff

def fingerprint(cases, events):
    return hashlib.sha256(json.dumps([cases, events], sort_keys=True).encode()).hexdigest()
