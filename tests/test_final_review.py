"""Focused checks for the final calibration and presentation changes."""
import json
import unittest
from collections import Counter, defaultdict
from datetime import timedelta
from scaleflow.datasets import load_dataset,ROOT
from scaleflow.engine import dt,STAGES,snapshot,metrics,attention,validate
from scaleflow.presentation import journey_counts,filter_attention,selected_case,history_rows,STEP_NAMES
from scaleflow.investigation import EvidenceTools,example_report

def independent_counts(cases,events,cutoff):
    histories=defaultdict(list)
    for event in events:
        if dt(event['timestamp'])<=dt(cutoff):
            histories[event['case_id']].append(event)
    stages=Counter()
    overdue=0
    for case in cases:
        if dt(case['request_date'])>dt(cutoff):
            continue
        history=histories[case['case_id']]
        if any(e['stage']==STAGES[-1] and e['event_type']=='completed' for e in history):
            continue
        latest=max((e for e in history if e['event_type']=='entered'),key=lambda e:(dt(e['timestamp']),e['sequence']))
        stages[latest['stage']]+=1
        overdue+=dt(case['expected_delivery_date'])<dt(cutoff)
    return stages,overdue

class FinalReviewTests(unittest.TestCase):
    def test_histories_reconcile_with_kpis_and_journey(self):
        for label in ['Normal Operations','Growing Demand','Operational Disruption']:
            cases,events,cutoff=load_dataset(label)
            validate(cases,events,STAGES,cutoff,True)
            for days in [0,7,30]:
                end=(dt(cutoff)-timedelta(days=days)).isoformat()
                counts,overdue=independent_counts(cases,events,end)
                summary=metrics(cases,events,end,30)
                self.assertEqual(sum(counts.values()),summary['cases_in_progress'])
                self.assertEqual(overdue,summary['overdue_cases'])
                self.assertEqual(dict(counts),{s:v['active'] for s,v in summary['stages'].items()})
                self.assertEqual(sum(s['waiting'] for s in journey_counts(summary)),summary['cases_in_progress'])
                self.assertFalse(any('delivered' in s['name'].lower() for s in journey_counts(summary)))
                visible=[e for e in events if dt(e['timestamp'])<=dt(end)]
                self.assertEqual(snapshot(cases,events,end),snapshot(cases,visible,end))
        c,e,t=load_dataset('Growing Demand')
        cfg=json.loads((ROOT/'scenarios.json').read_text())
        self.assertEqual(cfg['scenarios']['demand']['lab_service_hours'],cfg['scenarios']['normal']['lab_service_hours'])
        late=metrics(c,e,t,7)
        early=metrics(c,e,(dt(cfg['start'])+timedelta(days=28)).isoformat(),28)
        self.assertGreater(late['cases_in_progress'],early['cases_in_progress'])
        self.assertGreater(late['median_turnaround_hours'],early['median_turnaround_hours'])
        self.assertGreater(late['overdue_cases'],0)
        self.assertLess(late['overdue_cases'],20)
        self.assertFalse(any(r['operational_status']=='interrupted' for r in snapshot(c,e,t)))

    def test_filters_selection_and_readable_history(self):
        c,e,t=load_dataset('Operational Disruption')
        rows=attention(snapshot(c,e,t))
        chosen=rows[0]
        matches=filter_attention(rows,chosen['current_stage'],chosen['partner_location'],'Overdue',chosen['case_id'].lower())
        self.assertEqual([r['case_id'] for r in matches],[chosen['case_id']])
        self.assertEqual(selected_case(matches,{'rows':[0]})['case_id'],chosen['case_id'])
        self.assertIsNone(selected_case([],{'rows':[0]}))
        self.assertEqual(filter_attention(rows,search='no-such-case'),[])
        tools=EvidenceTools(c,e,t,'Last 30 Days')
        readable=history_rows(tools.get_case_history(chosen['case_id']),t)
        self.assertEqual(list(readable[0]),['Process step','Date entered','Date completed','Time spent or waiting'])
        self.assertEqual(readable[-1]['Date completed'],'—')
        self.assertIn('waiting',readable[-1]['Time spent or waiting'])
        self.assertEqual(readable[-1]['Process step'],STEP_NAMES[chosen['current_stage']])
        self.assertFalse(any('T' in r['Date entered'] and '2026-' in r['Date entered'] for r in readable))

    def test_concise_examples_keep_evidence_and_limits(self):
        for label in ['Growing Demand','Operational Disruption']:
            c,e,t=load_dataset(label)
            tools=EvidenceTools(c,e,t,'Last 30 Days')
            stage=attention(tools.rows)[0]['current_stage']
            report=example_report(tools,stage)
            self.assertLessEqual(len(report['what_we_found']),3)
            self.assertTrue(report['missing'])
            self.assertEqual(set(report['case_ids']),{r['case_id'] for r in attention(tools.rows,stage)})
            self.assertTrue(report['evidence_details']['recorded_notes'])
            self.assertEqual(len(report['trace']),3)
            self.assertTrue(all(len(s)<180 for s in report['follow_ups']))

if __name__=='__main__':
    unittest.main()
