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

    def test_intent_parser(self):
        self.assertEqual(ga.parse_intent(['save']),('save',None))
        self.assertEqual(ga.parse_intent(['new','feature/test']),('new','feature/test'))
        self.assertEqual(ga.parse_intent(['undo my last commit but keep my code']),('undo-private',None))
        with self.assertRaises(SystemExit): ga.parse_intent(['delete everything'])
    def test_intent_main_menu_five(self):
        with patch.object(ga,'menu',return_value=None) as m: ga.dispatch_intent(self.project,True)
        self.assertEqual([x[0] for x in m.call_args.args[1]],['save','update','new','combine','fix'])
    def test_intent_local_save(self):
        (self.project/'app.py').write_text('new local change\n')
        with patch('builtins.input',side_effect=['1','STAGE','n','saved locally','COMMIT']): ga.dispatch_intent(self.project,True,'save')
        self.assertEqual(self.git('log','-1','--format=%s'),'saved locally')
    def test_intent_new_branch_clean(self):
        with patch('builtins.input',return_value='CREATE'): ga.dispatch_intent(self.project,True,'new','feature/test')
        self.assertEqual(ga.branch(),'feature/test')
    def test_intent_new_branch_dirty_carry(self):
        (self.project/'app.py').write_text('unfinished\n'); (self.project/'new.txt').write_text('new\n'); h=ga.head()
        with patch('builtins.input',side_effect=['1','CREATE']): ga.dispatch_intent(self.project,True,'new','feature/test')
        self.assertEqual(ga.branch(),'feature/test'); self.assertEqual(ga.head(),h); self.assertEqual((self.project/'app.py').read_text(),'unfinished\n'); self.assertTrue((self.project/'new.txt').exists())
    def test_intent_conflict_routing(self):
        self.divergent()
        with patch('builtins.input',side_effect=['5','main','MERGE']),self.assertRaises(SystemExit): ga.branch_menu(self.project)
        with patch.object(ga,'conflict_menu') as m, patch.object(ga,'intent_save') as save: ga.dispatch_intent(self.project,True,'save')
        m.assert_called_once_with(self.project); save.assert_not_called()
    def test_intent_unknown_no_mutation(self):
        h=ga.head()
        with self.assertRaises(SystemExit): ga.parse_intent(['reset','hard'])
        self.assertEqual(ga.head(),h)
    def test_intent_unregistered_local(self):
        self.git('remote','add','origin','https://github.com/user/repo.git')
        (self.project/'app.py').write_text('local only\n')
        with patch('builtins.input',side_effect=['2','STAGE','n','local','COMMIT']),patch.object(ga,'identity',side_effect=AssertionError('No network for local save')): ga.dispatch_intent(self.project,True,'save')
        self.assertEqual(self.git('log','-1','--format=%s'),'local')
    def remote_fixture(self, conflict=False, diverge=False):
        h=ga.head(); self.git('switch','-c','remote-work')
        p=self.project/('app.py' if conflict else 'remote.txt'); p.write_text('remote change\n'); self.git('add','--',p.name); self.git('commit','-m','remote change'); sha=ga.head()
        self.git('switch','main')
        if diverge:
            (self.project/'local.txt').write_text('local commit\n'); self.git('add','local.txt'); self.git('commit','-m','local commit'); h=ga.head()
        url='https://github.com/user/repo.git'; self.git('remote','add','origin',url)
        return (url,'user/repo','user',{},'/usr/bin/false',{'id':42},'main',h,sha)
    def test_intent_update_clean(self):
        snap=self.remote_fixture()
        with patch.object(ga,'remote_snapshot',return_value=snap),patch.object(ga,'snapshot_check'),patch('builtins.input',return_value='UPDATE'): ga.intent_update(self.project)
        self.assertEqual(ga.head(),snap[-1]); self.assertTrue((self.project/'remote.txt').exists())
    def test_intent_update_dirty_restore(self):
        snap=self.remote_fixture(); (self.project/'app.py').write_text('unfinished\n'); self.git('add','app.py'); (self.project/'app.py').write_text('more unfinished\n')
        with patch.object(ga,'remote_snapshot',return_value=snap),patch.object(ga,'snapshot_check'),patch('builtins.input',side_effect=['1','UPDATE']): ga.intent_update(self.project)
        self.assertEqual(ga.head(),snap[-1]); self.assertEqual((self.project/'app.py').read_text(),'more unfinished\n'); self.assertEqual(self.git('show',':app.py'),'unfinished'); self.assertEqual(len(ga.stash_entries()),1)
    def test_intent_update_conflict_keeps_stash(self):
        snap=self.remote_fixture(conflict=True); (self.project/'app.py').write_text('unfinished\n')
        with patch.object(ga,'remote_snapshot',return_value=snap),patch.object(ga,'snapshot_check'),patch('builtins.input',side_effect=['1','UPDATE']): ga.intent_update(self.project)
        self.assertEqual(ga.head(),snap[-1]); self.assertEqual(len(ga.stash_entries()),1); self.assertEqual(ga.conflict_paths(),['app.py'])
    def test_intent_update_untracked_blocked(self):
        snap=self.remote_fixture(); (self.project/'new.txt').write_text('private\n')
        with patch.object(ga,'remote_snapshot',return_value=snap),self.assertRaises(SystemExit): ga.intent_update(self.project)
        self.assertEqual(ga.head(),snap[-2]); self.assertTrue((self.project/'new.txt').exists()); self.assertFalse(ga.stash_entries())
    def test_intent_update_diverged_merge(self):
        snap=self.remote_fixture(diverge=True)
        with patch.object(ga,'remote_snapshot',return_value=snap),patch.object(ga,'snapshot_check'),patch('builtins.input',side_effect=['1','MERGE']): ga.intent_update(self.project)
        self.assertEqual(ga.head(),snap[-2]); self.assertIn('MERGE_HEAD',ga.ongoing())
        with patch('builtins.input',side_effect=['3','n','CONTINUE']): ga.conflict_menu(self.project)
        self.assertTrue(ga.ancestor(snap[-1],ga.head())); self.assertTrue(ga.ancestor(snap[-2],ga.head()))
    def test_intent_update_ignored_file_protected(self):
        (self.project/'.gitignore').write_text('remote.txt\n'); self.git('add','.gitignore'); self.git('commit','-m','ignore')
        h=ga.head(); self.git('switch','-c','remote-work'); (self.project/'remote.txt').write_text('tracked remote\n'); self.git('add','-f','remote.txt'); self.git('commit','-m','remote'); sha=ga.head(); self.git('switch','main'); (self.project/'remote.txt').write_text('private ignored\n')
        snap=('https://github.com/user/repo.git','user/repo','user',{},'/usr/bin/false',{'id':42},'main',h,sha)
        with patch.object(ga,'remote_snapshot',return_value=snap),patch.object(ga,'snapshot_check'),patch('builtins.input',return_value='UPDATE'),self.assertRaises(SystemExit): ga.intent_update(self.project)
        self.assertEqual(ga.head(),h); self.assertEqual((self.project/'remote.txt').read_text(),'private ignored\n')
    def test_intent_update_snapshot_changed(self):
        snap=self.remote_fixture()
        with patch.object(ga,'remote_snapshot',return_value=snap),patch.object(ga,'snapshot_check',side_effect=SystemExit('remote changed')),patch('builtins.input',return_value='UPDATE'),self.assertRaises(SystemExit): ga.intent_update(self.project)
        self.assertEqual(ga.head(),snap[-2])

    def test_v7_confirmation_case_and_retry(self):
        with patch('builtins.input',side_effect=['mistyped','commit']): ga.confirm('COMMIT','Confirm commit')
        with patch('builtins.input',side_effect=['delete Feature','delete feature']): ga.confirm('DELETE feature','Confirm branch')
        with patch('builtins.input',return_value='cancel'), self.assertRaises(SystemExit): ga.confirm('PUSH','Confirm upload')
    def test_v7_menu_invalid_retry(self):
        with patch('builtins.input',side_effect=['invalid','99','2']): self.assertEqual(ga.menu('Test',[('a','A'),('b','B')]),'b')
    def test_v7_graph_reachability(self):
        self.assertEqual(ga.reachable('inspect'),set(ga.GRAPH))
        self.assertTrue(all('exit' in ga.reachable(x) for x in ga.GRAPH))
        ga.graph_check()
    def test_v7_registry_search(self):
        for key,action in ga.ACTIONS.items(): self.assertIn(action,ga.search_actions(key))
        self.assertIn('stash-pop',[a.key for a in ga.search_actions('stash pop')])
        self.assertIn('branch-delete',[a.key for a in ga.search_actions('branch delete')])
        self.assertIn('merge-remote',[a.key for a in ga.search_actions('remote merge')])
    def test_v7_session_cancel_and_save(self):
        (self.project/'app.py').write_text('print(2)\n'); h=ga.head()
        with patch('builtins.input',side_effect=['cancel','1','1','STAGE','n','new work','commit','0']): ga.persistent_session(self.project,'local-save')
        self.assertNotEqual(ga.head(),h); self.assertEqual(self.git('log','-1','--format=%s'),'new work')
    def test_v7_session_error_stays_open(self):
        h=ga.head()
        with patch('builtins.input',side_effect=['0']): ga.persistent_session(self.project,'push')
        self.assertEqual(ga.head(),h)
        with ga.Session(self.project) as s:
            self.assertEqual(s.previous['state'],'exit'); self.assertIn('action-stopped',[x['event'] for x in s.previous['events']])
    def test_v7_interruption_journal_resume(self):
        with patch.object(ga,'run_action',side_effect=EOFError): ga.persistent_session(self.project,'local-save')
        with ga.Session(self.project) as s: self.assertEqual(s.previous['state'],'paused')
        with patch.object(ga,'run_action') as run,patch('builtins.input',return_value='0'): ga.persistent_session(self.project,'push')
        run.assert_not_called()
    def test_v7_conflict_guard(self):
        with patch.object(ga,'advanced_guard') as guard:
            with self.assertRaises(SystemExit): ga.run_action(self.project,True,['MERGE_HEAD'],'push')
            guard.assert_not_called()
    def test_v7_session_lock(self):
        with ga.Session(self.project):
            with self.assertRaises(SystemExit):
                with ga.Session(self.project): pass
    def test_v7_local_initialization(self):
        p=self.home/'new-project'; p.mkdir(); (p/'file.txt').write_text('local'); os.chdir(p)
        with patch('builtins.input',side_effect=['init','0']): ga.persistent_session(p,'init')
        self.assertTrue((p/'.git').is_dir()); self.assertIsNone(ga.head()); self.assertEqual(self.git('ls-files'),''); self.assertEqual(self.git('remote'),'')
    def test_v7_branch_delete_route(self):
        self.git('branch','old-branch')
        with patch('builtins.input',side_effect=['old-branch','delete old-branch']): ga.run_action(self.project,True,[],'branch-delete')
        self.assertNotIn('old-branch',ga.local_branches())
    def test_v7_block_home(self):
        os.chdir(self.home)
        with self.assertRaises(SystemExit): ga.boundary()
        self.assertFalse((self.home/'.git').exists())

if __name__=='__main__': unittest.main()
