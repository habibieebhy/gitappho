import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
HERE=Path(__file__).resolve().parent
CORE=Path(os.environ.get('GITAPPHO_TEST_CORE',str(HERE/'core.py'))).resolve()
from native_worker import legacy_menus
class Native(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup)
        self.home=Path(self.t.name);self.repo=self.home/'project';self.repo.mkdir()
        self.env=dict(os.environ,HOME=str(self.home),XDG_CONFIG_HOME=str(self.home/".config"),GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL=os.devnull)
        # core intentionally rejects custom GIT_CONFIG* variables, so use isolated HOME.
        for k in list(self.env):
            if k.startswith('GIT_CONFIG'):self.env.pop(k)
        self.git('init','-b','main');self.git('config','user.name','Tester');self.git('config','user.email','test@example.invalid');self.git('config','commit.gpgsign','false')
        (self.repo/'sample.txt').write_text('base\n');self.git('add','.');self.git('commit','-m','base')
    def git(self,*args):return subprocess.check_output(['git',*args],cwd=self.repo,env=self.env,stderr=subprocess.STDOUT,text=True).strip()
    def flow(self,key,answers,folder=None):
        p=subprocess.Popen([sys.executable,'-u',str(HERE/'bridge.py'),'workflow',str(CORE),key],cwd=folder or self.repo,env=self.env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        events=[];responses=iter(answers)
        try:
            for line in p.stdout:
                e=json.loads(line);events.append(e)
                if e['kind']=='prompt':
                    val=next(responses);p.stdin.write(json.dumps({'id':e['id'],'value':val})+'\n');p.stdin.flush()
            self.assertEqual(p.wait(timeout=10),0,p.stderr.read());self.assertEqual(events[-1]['kind'],'done');self.assertIsNone(next(responses,None));return events
        finally:
            if p.poll() is None:p.kill();p.wait()
            for f in (p.stdin,p.stdout,p.stderr):f.close()
    def test_commit_nested(self):
        (self.repo/'sample.txt').write_text('changed\n')
        ev=self.flow('save',['local','STAGE','n','native message','COMMIT'])
        self.assertEqual(self.git('log','-1','--format=%s'),'native message');self.assertEqual(self.git('status','--short'),'')
        self.assertEqual([e['mode'] for e in ev if e['kind']=='prompt'],['choice','confirm','choice','text','confirm'])
    def test_cancel_preserves_head(self):
        (self.repo/'sample.txt').write_text('changed\n');h=self.git('rev-parse','HEAD')
        self.flow('local-save',['CANCEL']);self.assertEqual(self.git('rev-parse','HEAD'),h);self.assertEqual(self.git('diff','--cached','--name-only'),'')
        self.flow('local-save',['STAGE','n','retry','COMMIT']);self.assertEqual(self.git('log','-1','--format=%s'),'retry')
    def test_conflict_nested(self):
        self.git('switch','-c','feature');(self.repo/'sample.txt').write_text('feature\n');self.git('commit','-am','feature');self.git('switch','main');(self.repo/'sample.txt').write_text('main\n');self.git('commit','-am','main')
        subprocess.run(['git','merge','feature'],cwd=self.repo,env=self.env,capture_output=True)
        self.assertTrue((self.repo/'.git/MERGE_HEAD').exists())
        e=self.flow('fix',['1','1']);self.assertTrue(any(x['kind']=='prompt' and x['mode']=='choice' and 'conflict' in x['text'].lower() for x in e))
        (self.repo/'sample.txt').write_text('resolved\n');self.flow('fix',['2','1','RESOLVE']);self.flow('fix',['3','n','CONTINUE']);self.assertFalse((self.repo/'.git/MERGE_HEAD').exists())
    def test_stash(self):
        (self.repo/'sample.txt').write_text('changed\n');self.flow('stash',['test','STASH']);self.assertEqual(self.git('status','--short'),'');self.flow('restore-stash',['1','RESTORE']);self.assertEqual((self.repo/'sample.txt').read_text(),'changed\n')
    def test_home_guard(self):
        ev=self.flow('save',[],self.home);self.assertFalse(any(x['kind']=='prompt' for x in ev));self.assertTrue(any('forbidden' in x.get('text','') for x in ev))
    def test_static_menu_coverage(self):self.assertEqual(len(legacy_menus(CORE)),9)
if __name__=='__main__':unittest.main(verbosity=2)
