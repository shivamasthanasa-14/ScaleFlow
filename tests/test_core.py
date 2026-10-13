import copy
import json
import tempfile
import unittest
from datetime import timedelta
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from scaleflow.datasets import ROOT, LABELS, CONFIG, load_dataset
from scaleflow.engine import dt, STAGES, snapshot, metrics, validate, stage_durations, attention
from scaleflow.investigation import EvidenceTools, example_report
from scaleflow.importer import import_workbook
from scaleflow.store import save_followup, load_followup
from scaleflow.agent import investigate

class CoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases, cls.events, cls.cutoff = load_dataset('Operational Disruption')

    def test_all_scenarios_and_file_integrity(self):
        import hashlib
        manifest = json.loads((ROOT/'data/manifest.json').read_text())
        for file, digest in manifest['files'].items():
            self.assertEqual(hashlib.sha256((ROOT/'data'/file).read_bytes()).hexdigest(), digest)
        for label in LABELS:
            c,e,t = load_dataset(label)
            self.assertTrue(180 <= len(c) <= 250)
            validate(c,e,STAGES,t,True)
        with self.assertRaises(ValueError):
            load_dataset('Unknown')

    def test_stage_duration_and_turnaround(self):
        for row in snapshot(self.cases, self.events, self.cutoff):
            durations = stage_durations(self.events, row['case_id'], self.cutoff)
            self.assertAlmostEqual(sum(durations.values())+row['waiting_hours'], row['elapsed_hours'])
            if row['actual_delivery_date']:
                self.assertEqual(row['waiting_hours'], 0)
                self.assertAlmostEqual(row['elapsed_hours'], (dt(row['actual_delivery_date'])-dt(row['request_date'])).total_seconds()/3600)

    def test_cutoffs_do_not_leak_events(self):
        for days in (7,30,60):
            t = (dt(self.cutoff)-timedelta(days=days)).isoformat()
            visible = [e for e in self.events if dt(e['timestamp'])<=dt(t)]
            self.assertEqual(snapshot(self.cases,self.events,t), snapshot(self.cases,visible,t))
            self.assertEqual(metrics(self.cases,self.events,t,7), metrics(self.cases,visible,t,7))

    def test_deadline_boundary_and_status_history(self):
        row = attention(snapshot(self.cases,self.events,self.cutoff))[0]
        deadline = row['expected_delivery_date']
        before = next(r for r in snapshot(self.cases,self.events,deadline) if r['case_id']==row['case_id'])
        after = next(r for r in snapshot(self.cases,self.events,(dt(deadline)+timedelta(seconds=1)).isoformat()) if r['case_id']==row['case_id'])
        self.assertFalse(before['overdue'])
        self.assertTrue(after['overdue'])
        normal_c, normal_e, t = load_dataset('Normal Operations')
        complete = next(r for r in snapshot(normal_c,normal_e,t) if r['actual_delivery_date'])
        historical = next(r for r in snapshot(normal_c,normal_e,(dt(complete['actual_delivery_date'])-timedelta(seconds=1)).isoformat()) if r['case_id']==complete['case_id'])
        self.assertIsNone(historical['actual_delivery_date'])

    def test_tool_validation_and_history(self):
        tools=EvidenceTools(self.cases,self.events,self.cutoff,'Last 30 Days')
        result=tools.get_delayed_cases(STAGES[2], 'Last 30 Days')
        case_id=result['cases'][0]['case_id']
        history=tools.get_case_history(case_id)
        self.assertTrue(all(dt(e['timestamp'])<=dt(self.cutoff) for e in history['events']))
        self.assertTrue(tools.get_exception_notes([case_id])[0]['notes'])
        for name,args in [('delete_cases',{}),('get_case_history',{'case_id':'fake'}),('get_exception_notes',{'case_ids':'bad'}),
                          ('get_delayed_cases',{'stage':STAGES[2],'reporting_period':'All Time'}),('get_case_history',{'case_id':case_id,'extra':1})]:
            with self.assertRaises(ValueError):
                tools.dispatch(name,args)
        report=example_report(tools,STAGES[2])
        self.assertIn('Deterministic',report['mode'])
        self.assertEqual(len(report['trace']),3)

    def test_contradictory_records_rejected(self):
        for altered in [self.events+[self.events[0]], self.events[1:], [dict(self.events[0], timestamp='2030-01-01T00:00:00')]+self.events[1:]]:
            with self.assertRaises(AssertionError):
                validate(self.cases,altered,STAGES,self.cutoff)

    def test_excel_import_and_invalid_events(self):
        from openpyxl import load_workbook
        blob=(ROOT/'templates/scaleflow_import.xlsx').read_bytes()
        c,e,t=import_workbook(blob)
        self.assertEqual(len(c),2)
        self.assertEqual(len(snapshot(c,e,t)),2)
        wb=load_workbook(BytesIO(blob))
        sheet=wb['Stage Events']
        sheet.append([cell.value for cell in sheet[2]])
        stream=BytesIO()
        wb.save(stream)
        with self.assertRaises(ValueError):
            import_workbook(stream.getvalue())

    def test_followup_persistence_and_context_isolation(self):
        (ROOT/'local').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT/'local') as temp:
            path=Path(temp)/'followups.sqlite3'
            save_followup('context-a','Ask for dispatch confirmation','Logistics','2026-10-15',{'mode':'example'},path)
            self.assertEqual(load_followup('context-a',path)['owner'],'Logistics')
            self.assertIsNone(load_followup('context-b',path))
            save_followup('context-a','Updated question','Operations','2026-10-16',{'mode':'example'},path)
            self.assertEqual(load_followup('context-a',path)['action'],'Updated question')
            with self.assertRaises(ValueError):
                save_followup('bad','', 'Owner','2026-10-15',{},path)

    def test_agent_does_not_accept_summary_without_tools(self):
        tools=EvidenceTools(self.cases,self.events,self.cutoff,'Last 30 Days')
        with patch('scaleflow.agent.local_models',return_value=['test-local']), patch('scaleflow.agent.request',return_value={'message':{'role':'assistant','content':'{}'}}):
            with self.assertRaisesRegex(RuntimeError, 'evidence types'):
                investigate(tools,STAGES[2],'test-local')

if __name__=='__main__':
    unittest.main()
