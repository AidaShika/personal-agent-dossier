#!/usr/bin/env python3
"""Export every Grok Bot profile as an agent-dossier/0.2 file (role only).
routines and memory are written as null = not exported (an empty list means "has none").
Usage: export_dossiers.py [out_dir]   Read-only on the agent folders; idempotent.
Exit code: 1 if any agent was BLOCKED (skipped over a sensitive pattern),
else 0 — a skip must never look like success (SPEC 5.2)."""
import glob, hashlib, json, os, re, sys, datetime

SRC = '/home/box/agent-data/agents/*/profile.json'
out = sys.argv[1] if len(sys.argv) > 1 else '/workspace/agent-dossier/out'
os.makedirs(out, exist_ok=True)
SCAN = [r'[\w.+-]+@(?!\d{1,3}(?:\.\d{1,3}){3}\b)[\w-]+\.[\w.]+', r'0\d{1,3}-\d{3,4}-\d{4}', r'\b\d{16}\b', r'sk-[A-Za-z0-9]{10,}', r'ghp_\w+', r'(?i)(password|passwd|密码)\s*[:：=]\s*\S+']

def split_name(full):
    m = re.match(r'^(.*?)\s*·\s*(.+)$', full or '')
    return (m.group(1), m.group(2)) if m else (full or '', '')

def q(s):  # JSON string is valid YAML, so quoting is safe for any text
    return json.dumps(s, ensure_ascii=False)

report = []
for p in sorted(glob.glob(SRC)):
    d = json.load(open(p))
    aid = os.path.basename(os.path.dirname(p))
    full = d.get('name') or ''
    name, title = split_name(full)
    title = title or d.get('title') or ''
    role = d.get('description') or ''
    hits = [x for x in SCAN if re.search(x, role)]
    if hits:
        report.append((aid, name, 'BLOCKED: sensitive pattern ' + ', '.join(hits)))
        continue
    n = lambda x: (x or '').replace('\r\n', '\n').strip()
    fp = hashlib.sha1('|'.join([n(name), n(title), n(role)]).encode('utf-8')).hexdigest()[:12]
    body = '\n'.join([
        '---', 'spec: agent-dossier/0.2', 'id: ' + aid, 'name: ' + q(name), 'title: ' + q(title),
        'status: active', 'exported_at: ' + datetime.date.today().isoformat(), 'source: grok-bot',
        'fingerprint: ' + fp, 'role: ' + q(role), 'routines: null', 'memory: null',
        'excluded: "routines and memory not exported by this script"', '---', '',
        '# ' + name + ' 交接档案（仅职能）', ''])
    open(os.path.join(out, re.sub(r'[^\w-]', '-', name.lower()) + '.dossier.md'), 'w').write(body)
    report.append((aid, name, 'ok ' + fp))
for r in report:
    print(*r, sep='\t')
blocked = [r for r in report if r[2].startswith('BLOCKED')]
if blocked:
    # SPEC 5.2: skipped agents are summarized loudly and the run fails,
    # so a skip can never pass unnoticed in automation.
    print('BLOCKED: %d of %d agent(s) skipped: %s' % (
        len(blocked), len(report), ', '.join(r[1] or r[0] for r in blocked)), file=sys.stderr)
    sys.exit(1)
