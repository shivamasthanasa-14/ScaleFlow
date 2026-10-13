"""One complete app smoke workflow; uses a temporary follow-up database."""
import json
import hashlib
import tempfile
from pathlib import Path
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
from scaleflow.datasets import ROOT, load_dataset, fingerprint
from scaleflow.engine import metrics

(ROOT/'local').mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(dir=ROOT/'local') as temp, patch('scaleflow.store.DEFAULT_DB',Path(temp)/'followups.sqlite3'):
    app=AppTest.from_file(str(ROOT/'app.py'),default_timeout=30).run()
    assert not app.exception, str(app.exception)
    observed=[]
    for label in ['Normal Operations','Growing Demand','Operational Disruption']:
        app.selectbox(key='dataset').set_value(label).run()
        assert not app.exception, str(app.exception)
        c,e,t=load_dataset(label)
        expected=metrics(c,e,t,30)
        assert app.metric[0].value==str(expected['cases_in_progress'])
        assert app.metric[3].value==str(expected['overdue_cases'])
        observed.append({'dataset':label,'open':app.metric[0].value,'overdue':app.metric[3].value})
    app.selectbox(key='period').set_value('Last 7 Days').run()
    assert not app.exception
    app.selectbox(key='period').set_value('Last 30 Days').run()
    # Exercise the compact attention filters before moving to investigation.
    next(s for s in app.selectbox if s.label=='Stage').set_value('Sample or diagnostic data received').run()
    next(s for s in app.selectbox if s.label=='Partner/location').set_value('North Clinic').run()
    next(s for s in app.selectbox if s.label=='Status').set_value('Interrupted').run()
    next(s for s in app.selectbox if s.label=='Records shown').set_value('All').run()
    assert not app.exception, str(app.exception)
    attention_frame=next(d.value for d in app.dataframe if 'Case ID' in d.value.columns)
    assert all(attention_frame['Partner/location']=='North Clinic')
    selected_id=attention_frame.iloc[0]['Case ID']
    next(s for s in app.text_input if s.label=='Search case ID').set_value(selected_id).run()
    attention_frame=next(d.value for d in app.dataframe if 'Case ID' in d.value.columns)
    assert len(attention_frame)==1 and attention_frame.iloc[0]['Case ID']==selected_id
    # Supply the same row-selection event emitted by the dataframe widget.
    source_cases,source_events,source_cutoff=load_dataset('Operational Disruption')
    view_identity=fingerprint(source_cases,source_events)[:12]+'_'+source_cutoff+'_Last 30 Days'
    table_identity=hashlib.sha256(json.dumps([selected_id]).encode()).hexdigest()[:12]
    selection_key='overview_'+view_identity+'_rows_'+table_identity
    app.session_state[selection_key]={'selection':{'rows':[0],'columns':[],'cells':[]}}
    app.run()
    assert not app.exception, str(app.exception)
    history_frame=next(d.value for d in app.dataframe if 'Date entered' in d.value.columns)
    assert 'Time spent or waiting' in history_frame.columns
    assert any(selected_id in m.value for m in app.markdown if 'Case history' in m.value)
    app.radio(key='page').set_value('Investigate Delays').run()
    assert not app.exception, str(app.exception)
    next(b for b in app.button if b.label=='Investigate Delays').click().run()
    assert not app.exception, str(app.exception)
    assert any('What we found' in s.value for s in app.subheader)
    next(i for i in app.text_input if i.label=='Responsible team or owner').set_value('Logistics Operations')
    next(b for b in app.button if b.label=='Save follow-up').click().run()
    assert not app.exception, str(app.exception)
    assert any('saved locally' in s.value for s in app.success)
    app.selectbox(key='dataset').set_value('Growing Demand').run()
    assert not app.exception
    assert not any('What we found' in s.value for s in app.subheader), 'Stale investigation leaked between scenarios'
    app.selectbox(key='dataset').set_value('Operational Disruption').run()
    assert not app.exception
    assert next(i for i in app.text_input if i.label=='Responsible team or owner').value=='Logistics Operations'
    result={'passed':True,'scenario_metrics':observed,'workflow':'Both pages, scenario/period switching, compact attention filters, case-ID search, all-record access, selected-row history, concise investigation, follow-up save/reload, and stale-result isolation.'}
    (ROOT/'verification').mkdir(exist_ok=True)
    (ROOT/'verification/app_smoke.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
