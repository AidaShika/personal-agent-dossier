#!/usr/bin/env python3
"""Dry-run importer for agent-dossier/0.1 and 0.2 -> Grok Bot.
Checks one dossier (file or Notion text) and prints what a real import would do, plus a loss/downgrade report.
It never creates or edits anything. Usage: import_dossier.py FILE [--agents-dir DIR]"""
import glob, hashlib, json, os, re, sys

try:
    import yaml
except ImportError:
    sys.exit('need pyyaml: python3 -m venv v && v/bin/pip install pyyaml')

SCAN = [r'[\w.+-]+@(?!\d{1,3}(?:\.\d{1,3}){3}\b)[\w-]+\.[\w.]+', r'0\d{1,3}-\d{3,4}-\d{4}', r'\b\d{16}\b', r'sk-[A-Za-z0-9]{10,}', r'ghp_\w+']
REQUIRED = ['spec', 'id', 'name', 'status', 'exported_at', 'source', 'fingerprint', 'role', 'routines', 'memory']
STATUS = {'active', 'handed-over', 'retired'}
KIND = {'rule', 'preference', 'decision', 'history'}

def fingerprint(name, title, role):
    n = lambda s: (s or '').replace('\r\n', '\n').strip()
    return hashlib.sha1('|'.join([n(name), n(title), n(role)]).encode('utf-8')).hexdigest()[:12]

def load(path):
    """Accept the three storage forms: a .dossier.md file with front matter,
    a bare YAML file, or text copied from a Notion page holding one ```yaml block."""
    text = open(path, encoding='utf-8').read()
    blocks = re.findall(r'```ya?ml\n(.*?)\n```', text, re.S)
    if len(blocks) > 1:
        sys.exit('FAIL: more than one yaml block (spec section 1)')
    if blocks:
        return yaml.safe_load(blocks[0])
    parts = text.split('---\n', 2)
    if len(parts) >= 3 and not parts[0].strip():
        return yaml.safe_load(parts[1])
    data = yaml.safe_load(text)
    if isinstance(data, dict) and 'spec' in data:
        return data
    sys.exit('FAIL: no dossier found (need front matter, a yaml block, or bare yaml)')

def main():
    args = sys.argv[1:]
    agents = '/home/box/agent-data/agents'
    if '--agents-dir' in args:
        i = args.index('--agents-dir'); agents = args[i + 1]; del args[i:i + 2]
    if len(args) != 1:
        sys.exit(__doc__)
    fm = load(args[0])
    errors, loss, plan, warns = [], [], [], []

    for k in REQUIRED:
        if k not in fm:
            errors.append('missing required field: ' + k)
    if errors:
        print('\n'.join('FAIL: ' + e for e in errors)); sys.exit(1)

    if fm['spec'] not in ('agent-dossier/0.1', 'agent-dossier/0.2'): errors.append('unsupported spec ' + str(fm['spec']))
    if fm['status'] not in STATUS: errors.append('bad status ' + str(fm['status']))
    fp = fingerprint(fm['name'], fm.get('title'), fm['role'])
    if fp != fm['fingerprint']: errors.append('fingerprint mismatch: file says %s, content hashes to %s' % (fm['fingerprint'], fp))

    texts = [fm['role']] + [str(m.get('fact', '')) for m in (fm['memory'] or [])] + [str(r.get('prompt', '')) for r in (fm['routines'] or [])]
    for t in texts:
        for pat in SCAN:
            if re.search(pat, t): errors.append('sensitive pattern %s found; import refused' % pat)
    for m in fm['memory'] or []:
        if m.get('kind') not in KIND: errors.append('memory kind invalid: ' + str(m.get('kind')))

    uuids = set(re.findall(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', fm['role'])) - {fm['id']}
    if uuids:
        listed = {str(r.get('id')) for r in (fm.get('refs') or [])}
        for u in sorted(uuids):
            warns.append('role mentions agent id %s%s; it cannot be resolved on another platform' % (u, '' if u in listed else ' and it is not listed in refs'))

    existing = None
    for p in glob.glob(os.path.join(agents, '*', 'profile.json')):
        if os.path.basename(os.path.dirname(p)) == fm['id']:
            existing = json.load(open(p))
    full = fm['name'] + (' · ' + fm['title'] if fm.get('title') else '')
    if existing is None:
        plan.append('CREATE bot "%s" (new bot; the target platform assigns a new id, source id %s kept as a note)' % (full, fm['id']))
    else:
        same = existing.get('description') == fm['role'] and existing.get('name') == full
        plan.append('NO CHANGE: bot %s already matches this dossier' % fm['id'] if same else 'UPDATE bot %s: name/description differ from the dossier' % fm['id'])

    # fields Grok Bot cannot take directly
    if fm.get('anti_jobs'): loss.append('anti_jobs (%d): no dedicated field; kept inside the description text only if already written there' % len(fm['anti_jobs']))
    if fm.get('group'): loss.append('group "%s": sidebar section is set at creation, not read from a file' % fm['group'])
    if fm['routines'] is None: loss.append('routines: not exported (null). This is NOT the same as none; keep the original dossier')
    elif fm['routines']: loss.append('routines (%d): recreated one by one with UpdateRoutine; ids will change' % len(fm['routines']))
    if fm['memory'] is None: loss.append('memory: not exported (null). This is NOT the same as none; the new bot starts empty, keep the original dossier')
    elif fm['memory']: loss.append('memory (%d facts): written with UpdateMemory by the new bot itself; dates become import date' % len(fm['memory']))
    if fm.get('skills'): loss.append('skills %s: skills are global; missing ones must be installed separately' % fm['skills'])
    if fm.get('excluded'): loss.append('excluded by exporter: ' + fm['excluded'])

    print('DRY RUN ' + os.path.basename(args[0]))
    print('platform level: L2 (Grok Bot: name/description update by id; memory dates and routine ids change)')
    print('checks:', 'PASS' if not errors else 'FAIL')
    for e in errors: print('  FAIL', e)
    for w in warns: print('  WARN', w)
    for p in plan: print('plan:', p)
    for l in loss: print('loss/downgrade:', l)
    sys.exit(1 if errors else 0)

main()
