"""Local reliability demonstration. No network calls or production credentials."""
import hashlib
import json
import math
import sqlite3
from urllib.parse import urlsplit, parse_qs

UTM_FIELDS = ('utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term')
CATEGORIES = {'vending', 'rental', 'service', 'general'}
ROUTES = {'vending': 'sales_queue', 'rental': 'rental_queue',
          'service': 'service_queue', 'general': 'manual_review'}

class Intake:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS leads (
            id TEXT PRIMARY KEY, digest TEXT NOT NULL, data TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'received', route TEXT, summary TEXT);
          CREATE TABLE IF NOT EXISTS outbox (
            lead_id TEXT PRIMARY KEY REFERENCES leads(id), payload TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0);
        ''')

    def close(self):
        self.db.close()

    def receive(self, data):
        if not isinstance(data, dict):
            raise ValueError('Expected an object')
        for key in ('request_id', 'cta_id', 'page_url'):
            if not isinstance(data.get(key), str) or not data[key].strip():
                raise ValueError('Missing ' + key)
        if len(data['request_id']) > 100 or len(data['cta_id']) > 100:
            raise ValueError('Identifier too long')
        url = urlsplit(data['page_url'])
        if url.scheme != 'https' or url.hostname not in {'bogmar.net', 'www.bogmar.net.pl', 'bogmar.net.pl'}:
            raise ValueError('Unexpected source page')
        if data.get('contact_consent') is not True:
            raise ValueError('Contact permission missing')
        if not any(isinstance(data.get(k), str) and data[k].strip() for k in ('email', 'phone')):
            raise ValueError('Contact channel missing')
        # Preserve only declared fields; arbitrary URL query parameters may contain secrets.
        query = parse_qs(url.query)
        clean = {k: data.get(k, '') for k in ('request_id', 'cta_id', 'name', 'email', 'phone', 'message')}
        if any(not isinstance(v, str) or len(v) > 10000 for v in clean.values()):
            raise ValueError('Invalid text field')
        clean['page_url'] = url._replace(query='', fragment='').geturl()
        clean['utm'] = {k: query[k][0] for k in UTM_FIELDS if k in query}
        clean['contact_consent'] = True
        raw = json.dumps(clean, ensure_ascii=False, sort_keys=True)
        digest = hashlib.sha256(raw.encode()).hexdigest()
        with self.db:
            old = self.db.execute('SELECT digest FROM leads WHERE id=?', (clean['request_id'],)).fetchone()
            if old:
                if old['digest'] != digest:
                    raise ValueError('Request ID reused with different contents')
                return {'id': clean['request_id'], 'duplicate': True}
            self.db.execute('INSERT INTO leads(id,digest,data) VALUES(?,?,?)',
                            (clean['request_id'], digest, raw))
        # Commit precedes any classifier call or notification work.
        return {'id': clean['request_id'], 'duplicate': False}

    def prepare(self, request_id, classifier):
        with self.db:
            row = self.db.execute('SELECT * FROM leads WHERE id=?', (request_id,)).fetchone()
            if row is None:
                raise KeyError(request_id)
            if row['status'] == 'prepared':
                return
            data = json.loads(row['data'])
            category, summary = 'general', 'Wymagana ocena przez pracownika.'
            if data['message'].strip():
                try:
                    # The supplied classifier is a test double in this demonstration.
                    # It receives message text, not contact details or UTM identifiers.
                    result = classifier(data['message'])
                    confidence = result.get('confidence')
                    if (result.get('category') in CATEGORIES and
                        isinstance(confidence, (int, float)) and not isinstance(confidence, bool) and
                        math.isfinite(confidence) and 0.8 <= confidence <= 1 and
                        isinstance(result.get('summary'), str) and 0 < len(result['summary']) <= 500):
                        category, summary = result['category'], result['summary']
                except Exception:
                    pass  # Intake remains available when the classification service fails.
            route = ROUTES[category]
            payload = {'request_id': request_id, 'route': route, 'summary': summary, 'source': data}
            self.db.execute('INSERT INTO outbox(lead_id,payload) VALUES(?,?)',
                            (request_id, json.dumps(payload, ensure_ascii=False)))
            self.db.execute("UPDATE leads SET status='prepared',route=?,summary=? WHERE id=?",
                            (route, summary, request_id))

    def deliver(self, sender):
        # One worker only. Sender must support the request ID as an idempotency key.
        for row in self.db.execute("SELECT * FROM outbox WHERE status='pending'").fetchall():
            with self.db:
                self.db.execute('UPDATE outbox SET attempts=attempts+1 WHERE lead_id=?', (row['lead_id'],))
            try:
                sender(json.loads(row['payload']), idempotency_key=row['lead_id'])
            except Exception:
                continue
            with self.db:
                self.db.execute("UPDATE outbox SET status='sent' WHERE lead_id=?", (row['lead_id'],))

    def records(self, table):
        if table not in ('leads', 'outbox'):
            raise ValueError('Invalid table')
        return [dict(r) for r in self.db.execute('SELECT * FROM ' + table)]
