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
        with patch.object(ga,'scan_history'),patch.object(ga,'approved',return_value=(url,slug,'user',os.environ.copy(),'/usr/bin/false',d)),patch.object(ga,'verify_repo',return_value=d),patch.object(ga,'network',side_effect=fake_network),patch('builtins.input',return_value='PUSH'):
            ga.push(self.project)
            self.assertEqual(self.git('--git-dir='+str(remote),'rev-parse','refs/heads/main'),ga.head())
            (self.project/'app.py').write_text('second'); self.git('commit','-am','next'); ga.push(self.project)
            self.assertEqual(self.git('--git-dir='+str(remote),'rev-parse','refs/heads/main'),ga.head())
    def test_registry(self):
        ga.save({str(self.project):{'account':'user','remote':'https://github.com/user/repo.git','repo_id':'42'}}); self.assertEqual(ga.load()[str(self.project)]['repo_id'],'42')

    def divergent(self):
        self.git('switch','-c','feature'); (self.project/'app.py').write_text('feature\n'); self.git('commit','-am','feature')
        self.git('switch','main'); (self.project/'app.py').write_text('main\n'); self.git('commit','-am','main'); self.git('switch','feature')
    def test_merge_conflict_continue(self):
        self.divergent()
        with patch('builtins.input',side_effect=['5','main','MERGE']),self.assertRaises(SystemExit): ga.branch_menu(self.project)
        self.assertEqual(ga.conflict_paths(),['app.py']); self.assertIn('MERGE_HEAD',ga.ongoing())
        (self.project/'app.py').write_text('resolved\n')
        with patch('builtins.input',side_effect=['2','1','RESOLVE']): ga.conflict_menu(self.project)
        with patch('builtins.input',side_effect=['3','n','CONTINUE']): ga.conflict_menu(self.project)
        self.assertFalse(ga.ongoing()); self.assertEqual(len(self.git('rev-list','--parents','-n','1','HEAD').split()),3)
    def test_rebase_conflict_abort(self):
        self.divergent(); h=ga.head()
        with patch('builtins.input',side_effect=['1','main','REWRITE']): ga.rewrite_menu(self.project)
        self.assertIn('rebase-merge',ga.ongoing()); self.assertEqual(ga.conflict_paths(),['app.py'])
        with patch('builtins.input',side_effect=['4','ABORT']): ga.conflict_menu(self.project)
        self.assertEqual(ga.head(),h); self.assertFalse(ga.ongoing())
    def test_rebase_conflict_continue(self):
        self.divergent()
        with patch('builtins.input',side_effect=['1','main','REWRITE']): ga.rewrite_menu(self.project)
        (self.project/'app.py').write_text('resolved\n')
        with patch('builtins.input',side_effect=['2','1','RESOLVE']): ga.conflict_menu(self.project)
        with patch('builtins.input',side_effect=['3','n','CONTINUE']): ga.conflict_menu(self.project)
        self.assertFalse(ga.ongoing()); self.assertTrue(ga.ancestor(self.git('rev-parse','main'),ga.head()))
    def test_stash_and_pop(self):
        (self.project/'app.py').write_text('unfinished\n'); (self.project/'new.txt').write_text('new\n')
        with patch('builtins.input',side_effect=['1','label','STASH']): ga.stash_menu(self.project)
        self.assertEqual((self.project/'app.py').read_text(),'print(1)\n'); self.assertTrue((self.project/'new.txt').exists())
        (self.project/'new.txt').unlink()
        with patch('builtins.input',side_effect=['3','1','RESTORE']): ga.stash_menu(self.project)
        self.assertEqual((self.project/'app.py').read_text(),'unfinished\n'); self.assertFalse(ga.stash_entries()); self.assertTrue(self.git('for-each-ref','refs/gitappho/checkpoints'))
    def test_stash_conflict_keeps_backup(self):
        (self.project/'app.py').write_text('unfinished\n')
        with patch('builtins.input',side_effect=['1','label','STASH']): ga.stash_menu(self.project)
        (self.project/'app.py').write_text('other\n'); self.git('commit','-am','other')
        with patch('builtins.input',side_effect=['3','1','RESTORE']): ga.stash_menu(self.project)
        self.assertEqual(len(ga.stash_entries()),1)
    def test_rewrite_main_blocked(self):
        (self.project/'app.py').write_text('change'); self.git('commit','-am','change')
        with patch('builtins.input',return_value='2'),self.assertRaises(SystemExit): ga.rewrite_menu(self.project)
    def test_rewrite_tagged_commit_blocked(self):
        self.git('switch','-c','feature'); (self.project/'app.py').write_text('change'); self.git('commit','-am','change'); self.git('tag','published')
        with patch('builtins.input',return_value='2'),self.assertRaises(SystemExit): ga.rewrite_menu(self.project)
    def test_soft_undo(self):
        self.git('switch','-c','feature'); base=ga.head(); (self.project/'app.py').write_text('change'); self.git('commit','-am','change')
        with patch('builtins.input',side_effect=['2','REWRITE']): ga.rewrite_menu(self.project)
        self.assertEqual(ga.head(),base); self.assertEqual(self.git('diff','--cached','--name-only'),'app.py')
    def test_restore_deleted(self):
        (self.project/'app.py').unlink()
        with patch('builtins.input',side_effect=['3','1','RESTORE']): ga.specific_changes(self.project)
        self.assertTrue((self.project/'app.py').is_file()); self.assertFalse(self.git('status','--porcelain'))
    def test_untrack_preserves_file(self):
        (self.project/'.gitignore').write_text('app.py\n')
        with patch('builtins.input',side_effect=['4','1','UNTRACK']): ga.specific_changes(self.project)
        self.assertTrue((self.project/'app.py').is_file()); self.assertNotIn('app.py',self.git('ls-files'))
    def test_clean_no_staging(self):
        with patch('builtins.input',side_effect=AssertionError('unexpected prompt')): self.assertEqual(ga.stage_commit(),ga.head())
    def test_scanner_missing_fails_closed(self):
        with patch.object(ga.shutil,'which',return_value=None),self.assertRaises(SystemExit): ga.scan_history(ga.head())
    def test_scanner_nonzero_fails_closed(self):
        with patch.object(ga.shutil,'which',return_value='/usr/bin/false'),self.assertRaises(SystemExit): ga.scan_history(ga.head())

    def test_cherry_pick_conflict(self):
        self.divergent(); other=self.git('rev-parse','main')
        with patch('builtins.input',side_effect=['1',other,'APPLY']): ga.specific_changes(self.project)
        self.assertIn('CHERRY_PICK_HEAD',ga.ongoing())
        with patch('builtins.input',side_effect=['4','ABORT']): ga.conflict_menu(self.project)
        self.assertFalse(ga.ongoing())
    def test_squash(self):
        self.git('switch','-c','feature'); base=ga.head()
        for text in ['one','two']:
            (self.project/'app.py').write_text(text); self.git('commit','-am',text)
        with patch('builtins.input',side_effect=['4','2','combined','REWRITE']): ga.rewrite_menu(self.project)
        self.assertEqual(self.git('rev-list','--count',base+'..HEAD'),'1'); self.assertEqual((self.project/'app.py').read_text(),'two')
    def test_amend_message(self):
        self.git('switch','-c','feature'); (self.project/'app.py').write_text('change'); self.git('commit','-am','old')
        with patch('builtins.input',side_effect=['3','new message','REWRITE']): ga.rewrite_menu(self.project)
        self.assertEqual(self.git('log','-1','--format=%s'),'new message')
    def test_bisect_reset(self):
        good=ga.head()
        for text in ['one','two','three']:
            (self.project/'app.py').write_text(text); self.git('commit','-am',text)
        h=ga.head()
        with patch('builtins.input',side_effect=[good,'BISECT']): ga.bisect_menu(self.project)
        self.assertIn('BISECT_START',ga.ongoing())
        with patch('builtins.input',side_effect=['5','RESET']): ga.bisect_menu(self.project)
        self.assertEqual(ga.head(),h); self.assertEqual(ga.branch(),'main'); self.assertFalse(ga.ongoing())
    def test_conflict_markers_rejected(self):
        self.divergent()
        with patch('builtins.input',side_effect=['5','main','MERGE']),self.assertRaises(SystemExit): ga.branch_menu(self.project)
        with patch('builtins.input',side_effect=['2','1']),self.assertRaises(SystemExit): ga.conflict_menu(self.project)
        self.assertEqual(ga.conflict_paths(),['app.py'])
    def test_checkpoint_rescue(self):
        h=ga.head(); ref=ga.checkpoint('test')
        with patch('builtins.input',side_effect=['y',h,'rescue/test','RESCUE']): ga.checkpoints_menu(self.project)
        self.assertEqual(self.git('rev-parse','rescue/test'),h); self.assertEqual(ga.branch(),'main')

if __name__=='__main__': unittest.main()
