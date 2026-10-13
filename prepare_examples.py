"""Explicit preparation; no generation of operational records."""
import hashlib
import json
import argparse
from scaleflow.datasets import ROOT, LABELS, load_dataset, fingerprint
from scaleflow.engine import PERIODS, attention, snapshot
from scaleflow.investigation import EvidenceTools, example_report

parser = argparse.ArgumentParser()
parser.add_argument('--refresh-examples', action='store_true', help='Refresh deterministic examples only; preserve real model outputs')
args = parser.parse_args()
for label in LABELS:
    cases, events, cutoff = load_dataset(label)
    for period in PERIODS:
        tools = EvidenceTools(cases, events, cutoff, period)
        for stage in dict.fromkeys(r['current_stage'] for r in attention(snapshot(cases, events, cutoff))):
            identity = json.dumps([fingerprint(cases, events), label, stage, cutoff, period])
            key = hashlib.sha256(identity.encode()).hexdigest()
            path = ROOT/'prepared'/f'{key}.json'
            previous = json.loads(path.read_text()) if path.exists() else None
            if not previous or args.refresh_examples and not previous.get('verified_tool_selection'):
                path.write_text(json.dumps(example_report(tools, stage), indent=2)+'\n')
print('Prepared evidence-derived examples; existing results retained.')
