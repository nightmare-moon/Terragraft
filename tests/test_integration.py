"""Opt-in live PostgreSQL/API checks: set TERRAGRAFT_TEST_API=1 and TERRAGRAFT_TOKEN."""
import json
import os
import unittest
import uuid
from urllib.request import Request, urlopen
from urllib.error import HTTPError


@unittest.skipUnless(os.getenv('TERRAGRAFT_TEST_API') == '1', 'Requires running Docker stack')
class ApiIntegration(unittest.TestCase):
    def setUp(self):
        self.workspace = 'test-' + uuid.uuid4().hex[:16]
        self.root = os.getenv('TERRAGRAFT_URL', 'http://localhost:8080')
        self.token = os.environ['TERRAGRAFT_TOKEN']

    def request(self, method, path, data=None):
        body = json.dumps(data).encode() if data is not None else None
        req = Request(self.root+path, data=body, method=method,
                      headers={'Authorization': 'Bearer '+self.token, 'Content-Type': 'application/json'})
        try:
            with urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read() or b'{}')
        except HTTPError as e:
            return e.code, json.loads(e.read() or b'{}')

    def test_graph_lease_and_version_conflict(self):
        w = self.workspace
        a, first = self.request('POST', '/api/operations/plan',
                                {'workspace':w,'label':'a','write_set':['vpc'],'ttl_seconds':120})
        self.assertEqual(a, 200)
        self.assertEqual(self.request('POST', '/api/operations/plan',
                         {'workspace':w,'label':'b','write_set':['vpc']})[0], 409)
        self.assertEqual(self.request('POST', '/api/operations/plan',
                         {'workspace':w,'label':'b','write_set':['iam']})[0], 200)
        self.assertEqual(self.request('POST',f"/api/operations/{first['operation_id']}/commit",
                        {'changes':{'vpc':{'id':'vpc-test'}}})[0],200)
        self.assertEqual(self.request('GET',f'/api/resources/{w}')[1]['resources'][0]['address'],'vpc')

    def test_state_encryption_and_history_api(self):
        w = self.workspace
        state = {'version':4, 'serial':1, 'lineage':str(uuid.uuid4()),'resources':[]}
        status,_ = self.request('POST',f'/state/{w}',state)
        self.assertEqual(status, 200)
        status,history = self.request('GET',f'/api/history/{w}')
        self.assertEqual(status, 200)
        self.assertEqual(history['versions'][0]['serial'],1)
        self.assertEqual(self.request('POST',f'/state/{w}',{'version':4,'serial':0,
                                    'lineage':state['lineage'],'resources':[]})[0],409)

    def test_exclusive_state_lock_and_distinct_workspace(self):
        w = self.workspace
        lock = {'ID': str(uuid.uuid4()), 'Operation':'OperationTypeApply'}
        self.assertEqual(self.request('LOCK', f'/state/{w}', lock)[0], 200)
        self.assertEqual(self.request('LOCK', f'/state/{w}', {'ID':str(uuid.uuid4())})[0], 423)
        state = {'version': 4, 'serial': 1, 'lineage':str(uuid.uuid4()),'resources': []}
        self.assertEqual(self.request('POST', f'/state/{w}', state)[0], 423)
        # A different workspace can still be written under a separate lock.
        self.assertEqual(self.request('POST', f'/state/{w}-other', state)[0], 200)
        self.assertEqual(self.request('UNLOCK', f'/state/{w}', lock)[0], 200)
        self.assertEqual(self.request('POST', f'/state/{w}', state)[0], 200)
