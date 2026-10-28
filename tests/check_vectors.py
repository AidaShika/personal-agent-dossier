#!/usr/bin/env python3
"""Check any implementation of the fingerprint against tests/fingerprint-vectors.json."""
import hashlib, json, os, sys
def fp(name, title, role):
    n = lambda s: (s or '').replace('\r\n', '\n').strip()
    return hashlib.sha1('|'.join([n(name), n(title), n(role)]).encode('utf-8')).hexdigest()[:12]
d = json.load(open(os.path.join(os.path.dirname(__file__), 'fingerprint-vectors.json')))
bad = [v for v in d['vectors'] if fp(v['name'], v['title'], v['role']) != v['fingerprint']]
print('FAIL %d of %d' % (len(bad), len(d['vectors'])) if bad else 'PASS %d vectors' % len(d['vectors']))
sys.exit(1 if bad else 0)
