import json
import sqlite3
from datetime import date, datetime
from pathlib import Path
from contextlib import closing

DEFAULT_DB = Path(__file__).resolve().parents[1]/'local/followups.sqlite3'

def connect(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.execute('CREATE TABLE IF NOT EXISTS followups (context TEXT PRIMARY KEY, payload TEXT NOT NULL)')
    return connection

def save_followup(context, action, owner, deadline, report, path=None):
    if not action.strip() or not owner.strip():
        raise ValueError('Follow-up text and responsible team/owner are required')
    date.fromisoformat(str(deadline))
    payload = dict(action=action.strip(), owner=owner.strip(), deadline=str(deadline), report=report,
                   saved_at=datetime.now().astimezone().isoformat())
    with closing(connect(path or DEFAULT_DB)) as db, db:
        db.execute('INSERT INTO followups(context,payload) VALUES (?,?) ON CONFLICT(context) DO UPDATE SET payload=excluded.payload',
                   (context, json.dumps(payload)))
    return payload

def load_followup(context, path=None):
    with closing(connect(path or DEFAULT_DB)) as db:
        row = db.execute('SELECT payload FROM followups WHERE context=?', (context,)).fetchone()
    return json.loads(row[0]) if row else None
