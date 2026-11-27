import contextlib
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import gitappho as ga

class Tests(unittest.TestCase):
    def setUp(self):
        self.old=Path.cwd(); self.tmp=tempfile.TemporaryDirectory(); self.home=Path(self.tmp.name).resolve(); self.project=self.home/'project'; self.project.mkdir(); os.chdir(self.project)
        self.patcher=patch.multiple(ga,HOME=self.home,CONFIG=self.home/'.config/gitappho',REGISTRY=self.home/'.config/gitappho/projects.json'); self.patcher.start()
        self.git('init','-b','main'); self.git('config','user.name','Tester'); self.git('config','user.email','tester@example.test'); self.git('config','commit.gpgsign','false')
        (self.project/'app.py').write_text('print(1)\n'); self.git('add','app.py'); self.git('commit','-m','initial')
    def tearDown(self):
        os.chdir(self.old); self.patcher.stop(); self.tmp.cleanup()
    def git(self,*args):
        return subprocess.run(['git',*args],check=True,text=True,capture_output=True).stdout.strip()
    def test_home(self):
        os.chdir(self.home)
        with self.assertRaises(SystemExit): ga.boundary()
    def test_inherited(self):
        (self.project/'sub').mkdir(); os.chdir(self.project/'sub')
        with self.assertRaises(SystemExit): ga.boundary()
    def test_parent_repo(self):
        self.git('-C',str(self.home),'init','-b','main')
        with self.assertRaises(SystemExit): ga.boundary()
    def test_protected(self):
        p=self.home/'Downloads'/'site'; p.mkdir(parents=True); os.chdir(p)
        with self.assertRaises(SystemExit): ga.boundary()
    def test_new_project(self):
        p=self.home/'new'; p.mkdir(); os.chdir(p); self.assertEqual(ga.boundary(),(p,False))
    def test_unregistered(self):
        self.git('remote','add','origin','https://github.com/user/repo.git')
        with self.assertRaises(SystemExit): ga.approved(self.project)
    def test_mismatched_remote(self):
        self.git('remote','add','origin','https://github.com/user/repo.git'); self.git('remote','set-url','--push','origin','https://github.com/other/repo.git')
        with self.assertRaises(SystemExit): ga.remote_info()
    def test_sensitive(self):
        with self.assertRaises(SystemExit): ga.sensitive(['src/.env'])
    def test_commit_selected(self):
        (self.project/'app.py').write_text('print(2)\n'); (self.project/'new.py').write_text('new\n'); (self.project/'ignored.txt').write_text('unselected\n')
        with patch('builtins.input',side_effect=['2','STAGE','n','change','COMMIT']): ga.stage_commit()
        self.assertIn('new.py',self.git('ls-files')); self.assertNotIn('ignored.txt',self.git('ls-files'))
    def test_cancel_stage(self):
        (self.project/'app.py').write_text('change'); h=ga.head()
        with patch('builtins.input',return_value='NO'), self.assertRaises(SystemExit): ga.stage_commit()
        self.assertEqual(ga.head(),h); self.assertEqual(self.git('diff','--cached','--name-only'),'')
    def test_initial_commit(self):
        p=self.home/'new'; p.mkdir(); os.chdir(p); self.git('init','-b','main'); self.git('config','user.name','Tester'); self.git('config','user.email','tester@example.test'); self.git('config','commit.gpgsign','false'); (p/'README.md').write_text('hi')
        with patch('builtins.input',side_effect=['1','STAGE','n','initial','COMMIT']): ga.stage_commit()
        self.assertTrue(ga.head())
    def test_branch_merge(self):
        with patch('builtins.input',side_effect=['1','main','feature/test','CREATE']): ga.branch_menu(self.project)
        self.assertEqual(ga.branch(),'feature/test'); (self.project/'app.py').write_text('print(3)\n'); self.git('commit','-am','feature')
        with patch('builtins.input',side_effect=['2','main','SWITCH']): ga.branch_menu(self.project)
        with patch('builtins.input',side_effect=['5','feature/test','MERGE','n','COMMIT']): ga.branch_menu(self.project)
        self.assertEqual(len(self.git('rev-list','--parents','-n','1','HEAD').split()),3)
        with patch('builtins.input',side_effect=['6','feature/test','DELETE feature/test']): ga.branch_menu(self.project)
        self.assertNotIn('feature/test',ga.local_branches())
    def test_push_real_git_fake_github(self):
        remote=self.home/'remote.git'; self.git('init','--bare',str(remote)); self.git('remote','add','origin','https://github.com/user/repo.git'); url='https://github.com/user/repo.git'; slug='user/repo'; d={'id':42,'visibility':'private'}
        realnet=ga.network
        def fake_network(gh,env,*args,**kwargs):
            return realnet(gh,env,*(str(remote) if a==url else a for a in args),**kwargs)
        with patch.object(ga,'approved',return_value=(url,slug,'user',os.environ.copy(),'/usr/bin/false',d)),patch.object(ga,'verify_repo',return_value=d),patch.object(ga,'network',side_effect=fake_network),patch('builtins.input',return_value='PUSH'):
            ga.push(self.project)
            self.assertEqual(self.git('--git-dir='+str(remote),'rev-parse','refs/heads/main'),ga.head())
            (self.project/'app.py').write_text('second'); self.git('commit','-am','next'); ga.push(self.project)
            self.assertEqual(self.git('--git-dir='+str(remote),'rev-parse','refs/heads/main'),ga.head())
    def test_registry(self):
        ga.save({str(self.project):{'account':'user','remote':'https://github.com/user/repo.git','repo_id':'42'}}); self.assertEqual(ga.load()[str(self.project)]['repo_id'],'42')

if __name__=='__main__': unittest.main()
