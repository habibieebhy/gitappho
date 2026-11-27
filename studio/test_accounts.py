import os, json, sys, unittest, tempfile, subprocess
from pathlib import Path
from unittest.mock import patch
from collections import deque
from accounts import classify, GRAPH, list_saved
from test_native import Native
from bridge import load_core,snapshot
CORE=Path(os.environ.get('GITAPPHO_TEST_CORE',str(Path(__file__).parent/'core.py'))).resolve()
class AccountTests(Native):
    # Inherited tests also ensure no regressions in normal workflows.
    def setup_gh(self, mode='ok'):
        b=self.home/'bin';b.mkdir(); gh=b/'gh'
        gh.write_text('''#!/usr/bin/env python3
import os, sys, json
args=sys.argv[1:]; mode=os.environ.get('FAKE_GH_MODE'); token=os.environ.get('GH_TOKEN')
if args[:2]==['auth','status']:
 print(json.dumps({'hosts':{'github.com':[{'login':'alice','token':'DONT_DISPLAY_TEST_SECRET'},{'login':'bob'}]}}));sys.exit(0)
if args[:2]==['auth','token']:
 user=args[args.index('--user')+1] if '--user' in args else 'alice'
 print('fake-'+user);sys.exit(0)
if args[0]=='api':
 if mode=='offline':print('dial tcp: connection refused',file=sys.stderr);sys.exit(1)
 if mode=='sso':print('HTTP 403: SAML SSO required',file=sys.stderr);sys.exit(1)
 if mode=='auth':print('HTTP 401: Bad credentials',file=sys.stderr);sys.exit(1)
 if 'user' in args:print(token.removeprefix('fake-'));sys.exit(0)
 print(json.dumps({'id':42,'full_name':'ExampleOrg/repo','permissions':{'push':mode!='readonly'},'visibility':'private'}));sys.exit(0)
sys.exit(2)
''');gh.chmod(0o700)
        self.env.update(PATH=str(b)+os.pathsep+self.env['PATH'],FAKE_GH_MODE=mode)
        self.git('remote','add','origin','https://github.com/ExampleOrg/repo.git')
        d=self.home/'.config/gitappho';d.mkdir(parents=True)
        self.registry=d/'projects.json';self.registry.write_text(json.dumps({str(self.repo):{'remote':'https://github.com/ExampleOrg/repo.git','account':'alice','repo_id':'42'}}))
    def test_account_rebind(self):
        self.setup_gh(); ev=self.flow('accounts-hub',['choose','account:bob','REGISTER',''])
        self.assertEqual(json.loads(self.registry.read_text())[str(self.repo)]['account'],'bob')
        self.assertNotIn('DONT_DISPLAY_TEST_SECRET',str(ev));self.assertNotIn('fake-bob',str(ev))
        self.assertEqual(self.git('remote','get-url','origin'),'https://github.com/ExampleOrg/repo.git')
    def test_sso_does_not_change_binding(self):
        self.setup_gh('sso');ev=self.flow('accounts-hub',['choose','account:bob',''])
        self.assertIn('SSO',str(ev));self.assertEqual(json.loads(self.registry.read_text())[str(self.repo)]['account'],'alice')
    def test_readonly_does_not_change_binding(self):
        self.setup_gh('readonly');ev=self.flow('accounts-hub',['choose','account:bob',''])
        self.assertIn('lacks verified write permission',str(ev));self.assertEqual(json.loads(self.registry.read_text())[str(self.repo)]['account'],'alice')
    def test_network_failure_keeps_local_commit(self):
        self.setup_gh('offline');(self.repo/'sample.txt').write_text('changed\n')
        ev=self.flow('save',['publish','STAGE','n','offline commit','COMMIT'])
        self.assertEqual(self.git('log','-1','--format=%s'),'offline commit');self.assertIn('Network or service failure',str(ev))
    def test_credentials_failure_keeps_local_commit(self):
        self.setup_gh('auth');(self.repo/'sample.txt').write_text('changed\n')
        ev=self.flow('save',['publish','STAGE','n','offline commit','COMMIT'])
        self.assertEqual(self.git('log','-1','--format=%s'),'offline commit');self.assertIn('Saved credential unavailable or rejected',str(ev))
    def test_browser_guidance(self):
        self.setup_gh();ev=self.flow('accounts-hub',['login',''])
        self.assertIn('second VS Code terminal',str(ev))
    def test_graph(self):
        def reachable(s):
            todo=deque([s]);seen={s}
            while todo:
                for v in GRAPH[todo.popleft()]:
                    if v not in seen:seen.add(v);todo.append(v)
            return seen
        self.assertEqual(reachable('inspect'),set(GRAPH));self.assertTrue(all('exit' in reachable(s) for s in GRAPH))
    def test_classify(self):
        for s,expect in [('HTTP 401','credentials'),('HTTP 403 SAML','sso'),('HTTP 403','permission'),('HTTP 404','missing'),('HTTP 429','network'),('dial tcp: timeout','network'),('other','unknown')]:self.assertEqual(classify(s),expect)
if __name__=='__main__':unittest.main(verbosity=2)
