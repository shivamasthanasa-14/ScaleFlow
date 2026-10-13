import hashlib
import html
import json
from datetime import datetime, timedelta, date, time
from pathlib import Path
from statistics import median
import altair as alt
import pandas as pd
import streamlit as st
from scaleflow.datasets import ROOT, LABELS, load_dataset, fingerprint
from scaleflow.engine import STAGES, PERIODS, dt, snapshot, metrics, attention, trend
from scaleflow.investigation import EvidenceTools, example_report, baseline_stage, report_markdown
from scaleflow.importer import import_workbook
from scaleflow.store import DEFAULT_DB, load_followup, save_followup
from scaleflow.workspace import workspace_db
from scaleflow.agent import local_models, investigate
from scaleflow.presentation import STEP_NAMES, CATEGORY_NAMES, journey_counts, date_text, status_text, filter_attention, selected_case, history_rows

st.set_page_config(page_title='ScaleFlow · VitaFlow Health', page_icon='◈', layout='wide')
st.markdown('''<style>
.block-container {padding-top:1.5rem; padding-bottom:2rem; max-width:1440px}
[data-testid="stSidebar"] {background:#10253D}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"], [data-testid="stSidebar"] label {color:#EDF4FB}
[data-testid="stMetric"] {background:white;border:1px solid #E1E7EF;border-radius:12px;padding:16px}
.journey {display:flex;align-items:center;gap:7px;overflow-x:auto;padding:6px 0 12px}
.journey-step {background:white;border:1px solid #DAE4EE;border-radius:10px;padding:12px;flex:1;min-width:120px;min-height:112px}
.journey-name {font-size:13px;color:#536B82;font-weight:600}
.journey-count {font-size:26px;font-weight:650;color:#13283F;margin-top:6px}
.journey-sub {font-size:12px;color:#697B8F}
.journey-arrow {font-size:22px;color:#177F86;flex-shrink:0}
.journey-finished {background:#EAF5F3;border-color:#BFDCD5}
.eyebrow {color:#177F86;font-size:12px;letter-spacing:1.4px;font-weight:650}
h1 {font-size:2rem!important} h3 {font-size:1.1rem!important}
</style>''', unsafe_allow_html=True)

@st.cache_data
def sample(label, revision):
    return load_dataset(label)

def table(rows):
    return pd.DataFrame([{'Case ID': r['case_id'], 'Process step': STEP_NAMES[r['current_stage']],
                          'Waiting days': round(r['waiting_hours']/24, 1), 'Delivery deadline': date_text(r['expected_delivery_date']),
                          'Status': status_text(r), 'Partner/location': r['partner_location']} for r in rows])

def show_history(case_id, tools):
    history = tools.get_case_history(case_id)
    st.markdown(f'**Case history · {case_id}**')
    st.dataframe(pd.DataFrame(history_rows(history, tools.cutoff)), hide_index=True, width='stretch')
    notes = [e for e in history['events'] if e['event_type']=='note']
    if notes:
        with st.expander('Recorded notes · '+case_id):
            for note in notes:
                st.write(date_text(note['timestamp'])+' · '+note.get('note',''))
    with st.expander('Advanced Details · '+case_id):
        st.dataframe(pd.DataFrame(history['events']), hide_index=True, width='stretch')

def attention_view(records, tools, prefix):
    filters = st.columns([1.2,1.1,1.1,1.2])
    stage_filter = filters[0].selectbox('Stage', ['All stages']+list(dict.fromkeys(r['current_stage'] for r in records)),
                                      format_func=lambda s: STEP_NAMES.get(s,s), key=prefix+'_stage')
    partner_filter = filters[1].selectbox('Partner/location', ['All locations']+sorted({r['partner_location'] for r in records}), key=prefix+'_partner')
    status_filter = filters[2].selectbox('Status', ['All statuses','Overdue','Interrupted','Interrupted & overdue'], key=prefix+'_status')
    search = filters[3].text_input('Search case ID', key=prefix+'_search', placeholder='Optional')
    matching = filter_attention(records,stage_filter,partner_filter,status_filter,search)
    limit = st.selectbox('Records shown', [10,25,50,'All'], key=prefix+'_limit')
    shown = matching if limit=='All' else matching[:limit]
    st.caption(f'Showing {len(shown)} of {len(matching)} matching cases. Select a row to see its history.')
    if not shown:
        st.info('No cases match these filters.')
        return
    table_identity = hashlib.sha256(json.dumps([r['case_id'] for r in shown]).encode()).hexdigest()[:12]
    selection = st.dataframe(table(shown), hide_index=True, width='stretch', height=min(390,36*(len(shown)+1)+3),
                             on_select='rerun', selection_mode='single-row', key=prefix+'_rows_'+table_identity)
    selected = selected_case(shown, selection.selection)
    if selected:
        show_history(selected['case_id'],tools)

with st.sidebar:
    st.markdown('## ScaleFlow')
    st.caption('VitaFlow Health · Operations')
    page = st.radio('Workspace', ['Process Overview', 'Investigate Delays'], label_visibility='collapsed', key='page')
    st.divider()
    st.caption('Fictional diagnostic operations. No patient data or clinical results.')
    st.caption('Saved follow-ups belong to this session and are not retained after it ends.' if workspace_db() != DEFAULT_DB else 'Local workstation follow-ups persist.')
    with st.expander('Advanced Settings'):
        live = st.checkbox('Use local Ollama for investigations', key='live_mode')
        if st.button('Check installed models'):
            try:
                st.session_state.models = local_models()
                if not st.session_state.models:
                    st.info('No installed local model with tool support found.')
            except Exception as exc:
                st.warning('Ollama unavailable: '+str(exc))
        models = st.session_state.get('models', [])
        model = st.selectbox('Installed local model', models, key='model') if models else None
        st.caption('Tools read records only. Model findings require review. No model downloads.')
    with st.expander('Import operational records'):
        template = ROOT/'templates/scaleflow_import.xlsx'
        if template.exists():
            st.download_button('Download Excel template', template.read_bytes(), file_name=template.name)
        st.caption('Cases and Stage Events sheets. Timestamps use one local clock; stages must be continuous.')
        upload = st.file_uploader('Completed template', type=['xlsx'])
        if upload and st.button('Validate and preview'):
            try:
                imported = import_workbook(upload.getvalue())
                st.session_state.imported = imported
                st.session_state.import_hash = hashlib.sha256(upload.getvalue()).hexdigest()
                st.success(f'Validated {len(imported[0])} cases.')
            except Exception as exc:
                st.session_state.pop('imported', None)
                st.error('Import rejected: '+str(exc))
        imported = st.session_state.get('imported')
        if imported:
            st.dataframe(pd.DataFrame(imported[0]).head(5), hide_index=True)
            use_import = st.checkbox('Analyze validated upload', key='use_import')
        else:
            use_import = False

st.markdown('<div class="eyebrow">PROCESS MONITORING</div>', unsafe_allow_html=True)
top = st.columns([2, 1, 1])
label = top[0].selectbox('Choose Sample Data', list(LABELS), key='dataset')
period = top[1].selectbox('Reporting period', list(PERIODS), index=1, key='period')
data_revision = hashlib.sha256((ROOT/'data/manifest.json').read_bytes()).hexdigest()
cases, events, reference = st.session_state.imported if use_import else sample(label,data_revision)
source = 'Validated upload' if use_import else label
min_date = min(dt(c['request_date']).date() for c in cases)
max_date = dt(reference).date()
cutoff_date = top[2].date_input('Reporting cutoff', max_date, min_value=min_date, max_value=max_date,
                                key='cutoff_'+('import_'+st.session_state.get('import_hash', '')[:8] if use_import else LABELS[label]))
cutoff = min(datetime.combine(cutoff_date, time(23,59,59)), dt(reference)).isoformat()
rows = snapshot(cases, events, cutoff)
days = PERIODS[period]
summary = metrics(cases, events, cutoff, days)
previous = metrics(cases, events, (dt(cutoff)-timedelta(days=days)).isoformat(), days) if days and dt(cutoff)-timedelta(days=days) >= dt(min(c['request_date'] for c in cases)) else None
st.title(page)
st.caption(f'{source} · Blood sample pathway' if not use_import else f'{source} · Uploaded stage pathway')
st.caption(f'As of {dt(cutoff):%d %b %Y}. Waiting cases are shown now; delivered reports cover {period.lower()}.')
view_identity = fingerprint(cases,events)[:12]+'_'+cutoff+'_'+period

if page == 'Process Overview':
    cols = st.columns(4)
    definitions = [('Cases in Progress', 'cases_in_progress', False), ('Reports Delivered','reports_delivered',False),
                   ('Typical Processing Time','median_turnaround_hours',True), ('Overdue Cases','overdue_cases',False)]
    for col, (title,key,is_duration) in zip(cols, definitions):
        value = summary[key]
        shown = 'No completions' if value is None else f'{value/24:.1f} days' if is_duration else str(value)
        delta = None
        if previous and value is not None and previous[key] is not None:
            change = value-previous[key]
            delta = f'{change/24:+.1f} days vs previous period' if is_duration else f'{change:+d} vs previous date' if key in ('cases_in_progress','overdue_cases') else f'{change:+d} vs previous period'
        col.metric(title, shown, delta, delta_color='inverse' if key in ('median_turnaround_hours','overdue_cases') else 'off')
    if days and not previous:
        st.caption('Not enough earlier records for a previous-period comparison.')
    st.subheader('Diagnostic Process Flow')
    active_steps = journey_counts(summary)
    nodes = [f'<div class="journey-step"><div class="journey-name">{html.escape(s["name"])}</div><div class="journey-count">{s["waiting"]}</div><div class="journey-sub">waiting cases · {s["overdue"]} overdue</div></div>' for s in active_steps]
    nodes.append(f'<div class="journey-step journey-finished"><div class="journey-name">Reports delivered</div><div class="journey-count">{summary["reports_delivered"]}</div><div class="journey-sub">completed · {html.escape(period.lower())}</div></div>')
    st.markdown('<div class="journey">'+'<span class="journey-arrow" aria-label="then">→</span>'.join(nodes)+'</div>',unsafe_allow_html=True)
    st.caption(f'{sum(s["waiting"] for s in active_steps)} waiting cases = {summary["cases_in_progress"]} cases in progress. Review & report includes reports awaiting delivery.')
    left, right = st.columns(2)
    with left:
        st.subheader('Where Delays Are Occurring')
        frame = pd.DataFrame([{'Stage': STEP_NAMES[s], 'Overdue cases': summary['stages'].get(s, {}).get('overdue',0)} for s in STAGES])
        chart = alt.Chart(frame).mark_bar(color='#D28148', cornerRadiusEnd=3).encode(
            x=alt.X('Overdue cases:Q', axis=alt.Axis(tickMinStep=1)), y=alt.Y('Stage:N', sort=list(STEP_NAMES.values()), title=None), tooltip=['Stage', 'Overdue cases'])
        st.altair_chart(chart.properties(height=215), width='stretch')
    with right:
        st.subheader('Processing Time Trend')
        points = trend(cases, events, cutoff, days)
        if points:
            frame = pd.DataFrame(points)
            frame['Week of delivery'] = pd.to_datetime(frame['Week of delivery'])
            chart = alt.Chart(frame).mark_line(color='#177F86', point=True).encode(
                x=alt.X('Week of delivery:T', title='Delivery week'), y=alt.Y('Median days:Q', title='Typical processing time (days)'),
                tooltip=[alt.Tooltip('Week of delivery:T'), alt.Tooltip('Median days:Q', format='.1f'), 'Reports:Q'])
            st.altair_chart(chart.properties(height=215), width='stretch')
            st.caption('Delivered reports only. Hover to see how many reports each week includes.')
        else:
            st.info('No reports were delivered in this period.')
    st.subheader('Cases Requiring Attention')
    affected = attention(rows)
    if affected:
        attention_view(affected,EvidenceTools(cases,events,cutoff,period),'overview_'+view_identity)
    else:
        st.success('No overdue or interrupted cases at this cutoff.')
    with st.expander('Other case histories'):
        if rows:
            case_id = st.selectbox('Case ID', [r['case_id'] for r in rows], key='overview_case_'+fingerprint(cases, events)[:8])
            show_history(case_id,EvidenceTools(cases,events,cutoff,period))
else:
    affected = attention(rows)
    detected = [s for s in STAGES if any(r['current_stage']==s for r in affected)]
    if not detected:
        st.success('No stage has overdue or interrupted cases at this cutoff.')
        st.info('Choose another sample situation or cutoff to investigate recorded delays.')
    else:
        st.caption('Waiting for attention: '+', '.join(f"{STEP_NAMES[s]} ({sum(r['current_stage']==s for r in affected)})" for s in detected))
        stage = st.selectbox('Stage to investigate', detected, format_func=lambda s: STEP_NAMES[s], key='stage_'+source+'_'+cutoff)
        stage_cases = attention(rows, stage)
        tools = EvidenceTools(cases, events, cutoff, period)
        normal_cases, normal_events, _ = sample('Normal Operations',data_revision)
        baseline = baseline_stage(normal_cases, normal_events, cutoff, stage, period) if not use_import else {'median_hours': None, 'count': 0}
        detail = st.columns(3)
        overdue_count = sum(r['overdue'] for r in stage_cases)
        leading_count = overdue_count or sum(r['operational_status']=='interrupted' for r in stage_cases)
        leading_status = 'overdue' if overdue_count else 'interrupted'
        st.write(f"**{leading_count} {leading_status} {'case is' if leading_count==1 else 'cases are'} currently waiting at {STEP_NAMES[stage].lower()}.**")
        detail[0].metric('Cases needing attention', len(stage_cases))
        detail[1].metric('Typical time waiting', f"{median(r['waiting_hours'] for r in stage_cases)/24:.1f} days")
        detail[2].metric('Usual time for this step', f"{baseline['median_hours']/24:.1f} days" if baseline['median_hours'] is not None else 'Unavailable')
        st.caption(f"Usual time is based on {baseline['count']} cases that finished this step in normal operations. Current waits may continue." if not use_import else 'Normal comparison is unavailable for uploaded records.')
        categories = sorted({CATEGORY_NAMES.get(n.get('category'),n.get('category','other').replace('_',' ')) for r in stage_cases for n in r['notes'] if n['stage']==stage})
        st.caption('Recorded reasons: '+(', '.join(categories) if categories else 'No reason recorded for this step.'))
        with st.expander('Cases needing attention'):
            attention_view(stage_cases,tools,'investigation_'+stage+'_'+view_identity)
        identity = json.dumps([fingerprint(cases, events), source, stage, cutoff, period])
        key = hashlib.sha256(identity.encode()).hexdigest()
        context = f'{source} | {stage} | {period} | {cutoff}'
        if st.button('Investigate Delays', type='primary'):
            if live:
                if not model:
                    st.error('Check installed models in Advanced Settings first, or disable local Ollama to use an example.')
                else:
                    progress = st.empty()
                    try:
                        with st.spinner('Investigating recorded evidence…'):
                            report = investigate(tools, stage, model, progress=progress.caption)
                        st.session_state['report_'+key] = report
                    except Exception as exc:
                        st.error('Live investigation could not be verified: '+str(exc))
                        st.session_state['report_'+key] = example_report(tools, stage)
                    progress.empty()
            else:
                prepared_path = ROOT/'prepared'/f'{key}.json'
                st.session_state['report_'+key] = json.loads(prepared_path.read_text()) if prepared_path.exists() else example_report(tools, stage)
        saved = load_followup(key, path=workspace_db())
        report = st.session_state.get('report_'+key) or (saved.get('report') if saved else None)
        if report:
            st.caption(report['mode'])
            if report.get('verified_tool_selection'):
                st.caption('Model investigation. Review findings against the supporting evidence.')
            else:
                st.caption('Record-based example, not a completed AI investigation.')
            if report.get('verified_tool_selection'):
                # Preserve actual model claims and qualifications; collapse rather than rewrite them.
                lead = report.get('what_we_found', [])[:1]
                for item in lead:
                    st.write(item)
            left, right = st.columns(2)
            for col, sections in [(left,[('what_we_found','What we found'), ('contributing','What may be contributing')]),
                                  (right,[('missing','What information is missing'), ('follow_ups','Suggested operational follow-ups')])]:
                with col:
                    for field, title in sections:
                        st.subheader(title)
                        visible_items = report.get(field, [])[:2] if report.get('verified_tool_selection') else report.get(field, [])
                        for item in visible_items:
                            st.markdown('- '+item)
            with st.expander('Supporting cases and evidence'):
                st.caption('Affected cases: '+', '.join(report.get('case_ids', [])))
                if report.get('evidence_details'):
                    details = report['evidence_details']
                    low,high = details['waiting_range_days']
                    st.write(f'Waiting times range from {low:.1f} to {high:.1f} days.')
                    if details['case_ids_without_reason']:
                        st.write('No recorded reason: '+', '.join(details['case_ids_without_reason']))
                if report.get('verified_tool_selection'):
                    st.markdown(report_markdown(report,context))
                for call in report.get('trace', []):
                    st.write(f"**{call['tool']}** — {call['finding']}")
            with st.expander('Advanced Details · investigation'):
                for call in report.get('trace', []):
                    if call.get('result'):
                        st.json(call['result'], expanded=False)
                if report.get('evidence_details'):
                    st.json(report['evidence_details'],expanded=False)
            st.subheader('Prepare an operational follow-up')
            with st.form('followup_'+key):
                action = st.text_area('Follow-up text', value=saved['action'] if saved else '\n\n'.join(report.get('follow_ups', [])), height=120)
                a,b = st.columns(2)
                owner = a.text_input('Responsible team or owner', value=saved['owner'] if saved else '')
                deadline = b.date_input('Follow-up deadline', value=date.fromisoformat(saved['deadline']) if saved else dt(cutoff).date()+timedelta(days=2))
                if st.form_submit_button('Save follow-up'):
                    try:
                        saved = save_followup(key, action, owner, deadline, report, path=workspace_db())
                        st.success('Follow-up saved locally.')
                    except ValueError as exc:
                        st.error(str(exc))
            text = report_markdown(report, context)+'\n\n## Prepared follow-up\n'+action+'\n\nOwner: '+owner+'\nDeadline: '+str(deadline)
            st.download_button('Download investigation summary', text, file_name='scaleflow_investigation.md', mime='text/markdown')
            with st.expander('Copy summary'):
                st.code(text, language='markdown')
            if saved:
                st.caption('Saved '+saved['saved_at']+' · '+saved['owner'])
