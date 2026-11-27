#!/usr/bin/env python3
"""GitAppho 5.0: intent-driven, guarded Git workflows."""
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import datetime

HOME = Path.home().resolve()
CONFIG = HOME / '.config' / 'gitappho'
REGISTRY = CONFIG / 'projects.json'


def stop(message):
    raise SystemExit('STOP: ' + message)


def run(args, *, env=None, capture=True, check=True):
    p = subprocess.run(args, env=env, text=True, stdout=subprocess.PIPE if capture else None,
                       stderr=subprocess.PIPE if capture else None)
    if check and p.returncode:
        # Do not echo arbitrary subprocess output: it can contain credentials.
        stop(f'{Path(args[0]).name} command failed (exit {p.returncode}). Review authentication or repository state.')
    return p


def git(*args, **kw):
    return run(['git', '-c', 'core.fsmonitor=false', *args], **kw)


def out(*args):
    return git(*args).stdout.strip()


def gh_path():
    gh = shutil.which('gh')
    if not gh:
        stop('Install GitHub CLI with: brew install gh')
    return gh


def gh_env():
    env = os.environ.copy()
    for k in ('GH_TOKEN', 'GITHUB_TOKEN', 'GH_ENTERPRISE_TOKEN', 'GITHUB_ENTERPRISE_TOKEN', 'GH_HOST', 'GH_REPO', 'GH_DEBUG', 'GIT_TRACE', 'GIT_TRACE_CURL', 'GIT_CURL_VERBOSE', 'GIT_ASKPASS', 'SSH_ASKPASS'):
        env.pop(k, None)
    for k in list(env):
        if k.startswith('GIT_TRACE'):
            env.pop(k, None)
    env['GH_HOST'] = 'github.com'
    return env


def identity(account=None):
    gh = gh_path()
    env = gh_env()
    args = [gh, 'auth', 'token', '--hostname', 'github.com']
    if account:
        if not re.fullmatch(r'[A-Za-z0-9-]+', account):
            stop('Invalid GitHub username.')
        args.extend(['--user', account])
    token = run(args, env=env).stdout.strip()
    if not token:
        stop('No saved GitHub login. Run gitappho --login.')
    env['GH_TOKEN'] = token
    env['GIT_TERMINAL_PROMPT'] = '0'
    login = run([gh, 'api', '--hostname', 'github.com', 'user', '--jq', '.login'], env=env).stdout.strip()
    if not re.fullmatch(r'[A-Za-z0-9-]+', login):
        stop('Could not verify GitHub account.')
    if account and login.casefold() != account.casefold():
        stop('Saved account does not match the authenticated GitHub user.')
    return login, env, gh



def confirm(word, message):
    if input(f'{message}\nType {word} to continue: ').strip() != word:
        stop('Cancelled. No further actions performed.')


def boundary():
    for k in os.environ:
        if k.startswith('GIT_CONFIG') or k in {'GIT_DIR','GIT_WORK_TREE','GIT_INDEX_FILE','GIT_COMMON_DIR','GIT_OBJECT_DIRECTORY','GIT_ALTERNATE_OBJECT_DIRECTORIES','GIT_NAMESPACE','GIT_SHALLOW_FILE','GIT_REPLACE_REF_BASE','GIT_EXEC_PATH','GIT_QUARANTINE_PATH','GIT_GRAFT_FILE','GIT_ATTR_SOURCE'}:
            stop('Custom Git environment detected. Open a normal terminal.')
    root = Path.cwd().resolve()
    if HOME not in root.parents:
        stop('Home and paths outside your home are forbidden.')
    rel = root.relative_to(HOME)
    if rel.parts[0] in {'Downloads','Desktop','Library','Pictures','Movies','Music','Public','Applications'} or any(x.startswith('.') for x in rel.parts) or root in {HOME/'Documents', HOME/'Projects'}:
        stop('Protected or broad personal directory. Use a dedicated project folder.')
    marker = root/'.git'
    if (root/'HEAD').is_file() and (root/'objects').is_dir() and (root/'refs').is_dir(): stop('Bare Git repository directory blocked.')
    if marker.is_symlink() or (marker.exists() and not marker.is_dir()):
        stop('Linked worktrees or symbolic Git directories are not supported.')
    # Never silently attach to a parent repository, even for new-project publishing.
    for parent in root.parents:
        if (parent/'.git').exists() or (parent/'.git').is_symlink():
            stop('Parent Git repository detected. No nested or inherited repositories allowed.')
    if marker.is_dir():
        if Path(out('rev-parse','--show-toplevel')).resolve() != root or out('rev-parse','--is-bare-repository') != 'false':
            stop('Repository boundary mismatch.')
        if Path(out('rev-parse','--absolute-git-dir')).resolve() != marker:
            stop('External Git metadata directory blocked.')
        if (marker/'objects'/'info'/'alternates').exists() or (marker/'shallow').exists():
            stop('Shared object stores and shallow repositories are not supported.')
        if out('for-each-ref','--format=%(refname)','refs/replace'):
            stop('Git replacement refs detected.')
    return root, marker.is_dir()


def ongoing():
    states = [s for s in ('MERGE_HEAD','CHERRY_PICK_HEAD','REVERT_HEAD','rebase-merge','rebase-apply','sequencer','index.lock','BISECT_START') if Path(out('rev-parse','--git-path',s)).exists()]
    if out('ls-files','-u'): states.append('UNMERGED')
    return states


def idle():
    if ongoing(): stop('An operation is in progress. Choose recovery or resolve it manually.')


def branch():
    b = out('branch','--show-current')
    if not b: stop('Detached HEAD. Switch to a branch manually.')
    return b


def head():
    p = git('rev-parse','--verify','HEAD',check=False)
    return p.stdout.strip() if p.returncode == 0 else None


def clean():
    if out('status','--porcelain','--untracked-files=all'):
        stop('Working tree not clean. Save or review changes first; no automatic stash.')


def valid_branch(b):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_./-]*', b) or git('check-ref-format','refs/heads/'+b,check=False).returncode:
        stop('Invalid branch name.')
    return b


def slugcheck(s):
    if not re.fullmatch(r'[A-Za-z0-9-]+/[A-Za-z0-9_.-]+',s) or s.split('/')[1] in {'.','..'}:
        stop('Enter an explicit GitHub OWNER/REPO.')
    return s


def remote_info():
    if 'origin' not in out('remote').splitlines(): return None
    raw = out('config','--get-all','remote.origin.url')
    fetch = out('remote','get-url','--all','origin')
    push = out('remote','get-url','--push','--all','origin')
    if raw != fetch or fetch != push:
        stop('Multiple, rewritten or differing fetch/push URLs are blocked.')
    m = re.fullmatch(r'https://github\.com/([A-Za-z0-9-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?',raw)
    if not m: stop('Only explicit HTTPS github.com URLs without credentials are supported.')
    return raw, slugcheck('/'.join(m.groups()))


def config_guard():
    # Disallow settings that can redirect authentication, transport, or pushes.
    keys = git('config','--name-only','--list').stdout.lower().splitlines()
    allowed = {'credential.helper','credential.https://github.com.helper','credential.https://github.com/.helper'}
    for key in keys:
        if (key.startswith('url.') or key.startswith('http.') or key.startswith('filter.') or key.startswith('includeif.') or key.startswith('remote.origin.pushoption') or key.startswith('push.pushoption') or key == 'remote.origin.receivepack' or key == 'remote.origin.uploadpack' or key == 'core.sshcommand' or key == 'core.worktree' or (key.startswith('credential.') and key not in allowed and key.endswith(('.helper','.username')))):
            stop('Custom Git transport, filter or credential setting needs manual review: '+key.split('.')[0])


def load():
    if REGISTRY.is_symlink(): stop('Project registry cannot be a symbolic link.')
    if not REGISTRY.exists(): return {}
    data = json.loads(REGISTRY.read_text())
    if not isinstance(data,dict): stop('Invalid project registry.')
    return data


def save(data):
    if CONFIG.is_symlink() or CONFIG.parent.is_symlink(): stop('Unsafe configuration path.')
    CONFIG.mkdir(mode=0o700,parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.projects-',dir=CONFIG)
    try:
        with os.fdopen(fd,'w') as f: json.dump(data,f,indent=2); f.write('\n')
        os.replace(tmp,REGISTRY)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


def api(gh,env,path,*args):
    return json.loads(run([gh,'api','--hostname','github.com',path,*args],env=env).stdout)


def verify_repo(slug,env,gh):
    d=api(gh,env,'repos/'+slug)
    if d.get('full_name','').casefold()!=slug.casefold(): stop('Repository moved or redirected. Review canonical destination manually.')
    if d.get('archived') or d.get('disabled') or not (d.get('permissions') or {}).get('push'):
        stop('Selected account lacks verified write permission or repository is archived.')
    return d


def network(gh,env,*args,capture=True,check=True):
    helper='!'+shlex.quote(gh)+' auth git-credential'
    return git('-c','credential.helper=','-c','credential.https://github.com.helper=',
               '-c','credential.https://github.com/.helper=',
               '-c','credential.https://github.com.helper='+helper,
               '-c','http.followRedirects=false','-c','http.sslVerify=true',
               '-c','remote.origin.mirror=false','-c','push.followTags=false',
               '-c','push.recurseSubmodules=no', '-c','fetch.recurseSubmodules=false',
               *args,env=env,capture=capture,check=check)


def remote_refs(gh,env,url):
    p=network(gh,env,'ls-remote','--heads',url)
    refs={}
    for line in p.stdout.splitlines():
        sha,ref=line.split('\t',1)
        if not re.fullmatch('[0-9a-f]{40,64}',sha) or not ref.startswith('refs/heads/'): stop('Unexpected remote refs.')
        refs[ref[11:]]=sha
    return refs


def fetch_branch(gh,env,url,b,sha):
    network(gh,env,'fetch','--no-tags','--no-recurse-submodules',url,'refs/heads/'+b)
    if out('rev-parse','FETCH_HEAD')!=sha: stop('Remote branch changed. Retry.')
    return sha


def ancestor(a,b):
    return git('merge-base','--is-ancestor',a,b,check=False).returncode==0


def paths(*args):
    return [x for x in git(*args).stdout.split('\0') if x]


def sensitive(items):
    for p in items:
        name=Path(p).name.lower()
        if any(ord(c)<32 or ord(c)==127 for c in p): stop('Unusual filename requires manual review.')
        if (name=='.env' or name.startswith(('.env.','id_rsa','id_ed25519','rzp-key')) or name.endswith(('.pem','.key','.p12','.pfx','.kdbx','.sqlite','.db')) or any(x in name for x in ('credential','secret','password','private_key')) or any(x.lower() in {'.ssh','.aws','.gnupg','node_modules','library'} for x in Path(p).parts)):
            stop('Potentially sensitive or generated filename: '+repr(p)+'. Review manually.')


def choose_files(items):
    if not items: return []
    if len(items)>500: stop('Over 500 untracked files. Set up .gitignore and stage selected files manually.')
    for i,p in enumerate(items,1): print(f'{i:3} {p!r}')
    ans=input('Select NEW files by number (e.g. 1 3), ALL to select this displayed list, or Enter for none: ').strip()
    if not ans: return []
    if ans=='ALL': selected=items
    else:
        try:
            nums=[int(x) for x in ans.split()]
            if not all(1<=x<=len(items) for x in nums): raise ValueError()
            selected=list(dict.fromkeys(items[x-1] for x in nums))
        except ValueError: stop('Invalid file selection.')
    sensitive(selected)
    root=Path.cwd().resolve()
    for p in selected:
        f=root/p
        if not f.is_file() or f.is_symlink() or f.resolve()!=f or root not in f.parents:
            stop('Only regular, non-symlink files can be newly staged.')
        if f.stat().st_size>20*1024*1024: stop('New file larger than 20 MiB; review manually.')
    return selected


def review_index():
    changed=paths('diff','--cached','--name-only','-z','--diff-filter=ACMRT','--no-renames')
    sensitive(changed)
    for line in git('ls-files','--stage','-z').stdout.split('\0'):
        if line.startswith(('120000 ','160000 ')): stop('Symlinks or submodules in index require manual handling.')
    git('--no-pager','diff','--cached','--no-ext-diff','--no-textconv','--stat',capture=False)
    if input('Show full staged diff? [y/N]: ').lower()=='y':
        git('--no-pager','diff','--cached','--no-ext-diff','--no-textconv',capture=False)
    return out('write-tree')


def stage_commit():
    idle(); h=head(); b=branch()
    git('status','--short','--untracked-files=all',capture=False)
    sensitive(paths('diff','--name-only','-z','--diff-filter=ACMRT','--no-renames')+paths('diff','--cached','--name-only','-z','--diff-filter=ACMRT','--no-renames'))
    if h and not out('status','--porcelain','--untracked-files=all'):
        print('No changes to save.'); return h
    selected=choose_files(paths('ls-files','--others','--exclude-standard','-z'))
    if selected or (h and out('status','--porcelain','--untracked-files=no')):
        confirm('STAGE','Stage tracked modifications and the selected new files?')
        if h: git('add','-u','--','.')
        if selected: git('--literal-pathspecs','add','--',*selected)
    if git('diff','--cached','--quiet',check=False).returncode==0:
        if not h: stop('No files selected for the initial commit.')
        print('No staged changes.'); return h
    tree=review_index()
    msg=input('Commit message (blank cancels): ').strip()
    if not msg: stop('Cancelled; staged changes retained.')
    confirm('COMMIT','Create a local commit with these reviewed files?')
    if boundary()[0]!=Path.cwd() or head()!=h or branch()!=b or out('write-tree')!=tree: stop('Repository changed during review.')
    git('commit','-m',msg,capture=False)
    if out('rev-parse','HEAD^{tree}')!=tree: stop('Unexpected committed tree. No push.')
    return head()


def register(root,remote,slug,account=None):
    login,env,gh=identity(account)
    d=verify_repo(slug,env,gh)
    print(f'Project: {root}\nAccount: {login}\nRepository: {d["full_name"]}\nVisibility: {d.get("visibility")}')
    confirm('REGISTER','Approve this exact path, account and GitHub repository?')
    if boundary()[0]!=root or remote_info()!=(remote,slug): stop('Project or remote changed.')
    data=load(); data[str(root)]={'remote':remote,'account':login,'repo_id':str(d['id'])}; save(data)
    print('Registered.'); return login,env,gh,d


def approved(root):
    config_guard(); ri=remote_info()
    if not ri: stop('Connect or publish the repository first.')
    url,slug=ri; row=load().get(str(root))
    if not row or row.get('remote')!=url: stop('Register this exact project and remote first.')
    login,env,gh=identity(row['account']); d=verify_repo(slug,env,gh)
    if str(d['id'])!=str(row['repo_id']): stop('Repository ID changed.')
    return url,slug,login,env,gh,d


def push(root):
    idle(); b=branch(); h=head()
    if not h: stop('Create initial commit first.')
    url,slug,login,env,gh,d=approved(root)
    old=remote_refs(gh,env,url).get(b)
    if old:
        fetch_branch(gh,env,url,b,old)
        if not ancestor(old,h):
            print('Local-only / remote-only commits:',out('rev-list','--left-right','--count',h+'...'+old))
            stop('GitHub has changes you lack. Compare with GitHub (option 9); merge shared history or rebase only private commits. No force push.')
        if old==h: print('Already up to date.'); return
    # Inspect all outgoing commits (including intermediate versions, not just HEAD).
    span=h if not old else old+'..'+h
    if any(line.startswith(('120000 ','160000 ')) for line in git('ls-tree','-r',h).stdout.splitlines()): stop('Symlinks or submodules in outgoing tree require manual review.')
    files=paths('log','--format=','--name-only','-z','--no-renames','-m',span)
    sensitive([x.strip('\n') for x in files if x.strip('\n')])
    git('--no-pager','log','--oneline','--max-count=30',span,capture=False)
    print('Outgoing file paths:',len(set(files)))
    for f in sorted(set(files))[:500]: print(repr(f))
    if len(set(files))>500: stop('Too many outgoing paths for safe review; inspect manually.')
    print(f'Push {b} to {slug} as {login}; visibility: {d.get("visibility")}')
    scan_history(span)
    confirm('PUSH','Publish the reviewed local commits?')
    if boundary()[0]!=root or head()!=h or branch()!=b or remote_info()!=(url,slug): stop('Project changed during review.')
    if str(verify_repo(slug,env,gh)['id'])!=str(d['id']) or remote_refs(gh,env,url).get(b)!=old: stop('Remote changed; retry.')
    network(gh,env,'push','--no-follow-tags','--recurse-submodules=no',url,h+':refs/heads/'+b,capture=False)
    print('Push completed.')


def login_action():
    run([gh_path(),'auth','login','--hostname','github.com','--git-protocol','https','--web'],env=gh_env(),capture=False)


def pick_account():
    run([gh_path(),'auth','status','--hostname','github.com'],env=gh_env(),capture=False,check=False)
    user=input('GitHub username (Enter = active account, LOGIN = add account): ').strip()
    if user=='LOGIN': login_action(); user=input('Username (Enter = active): ').strip()
    return identity(user or None)


def publish(root,exists):
    if exists:
        idle(); config_guard()
        if out('remote'): stop('Existing remote found. Use Register or Connect; never replace it automatically.')
    login,env,gh=pick_account()
    default=re.sub(r'[^A-Za-z0-9_.-]','-',root.name)
    slug=slugcheck(input(f'New repository OWNER/NAME [{login}/{default}]: ').strip() or login+'/'+default)
    if slug.split('/')[0].casefold()!=login.casefold(): stop('Automatic creation is limited to your selected personal account; create organization repos on GitHub then connect.')
    print(f'Exact local directory: {root}\nGitHub destination: {slug}\nDefault: PRIVATE')
    visibility=input('Enter PRIVATE or PUBLIC [PRIVATE]: ').strip() or 'PRIVATE'
    if visibility not in ('PRIVATE','PUBLIC'): stop('Invalid visibility.')
    # Creation API is authoritative. A lookup failure never proves nonexistence.
    probe=run([gh,'api','--hostname','github.com','repos/'+slug],env=env,check=False)
    if probe.returncode==0: stop('Repository exists. Choose Connect existing repository.')
    confirm('PUBLISH','Approve this exact folder and repository creation (no upload until separate PUSH confirmation)?')
    if boundary()!=(root,exists): stop('Project boundary changed.')
    if not exists: git('init','-b','main')
    config_guard()
    if branch()!='main': stop('Initial publication requires main. Switch manually first.')
    # If an initial commit does not exist, review and commit selected files first.
    if not head() or out('status','--porcelain','--untracked-files=all'): stage_commit()
    if branch()!='main': stop('Initial publication requires main. Switch manually or use branch menu.')
    if out('remote'): stop('Remote was added during setup.')
    # gh creates empty repository; no --source, --push or --clone.
    run([gh,'repo','create',slug,'--'+visibility.lower()],env=env,capture=False)
    d=verify_repo(slug,env,gh); url='https://github.com/'+slug+'.git'
    if remote_refs(gh,env,url): stop('New remote is not empty. No connection or upload.')
    git('remote','add','origin',url)
    data=load(); data[str(root)]={'remote':url,'account':login,'repo_id':str(d['id'])}; save(data)
    print('Remote created and registered. Review outgoing commits next.')
    push(root)


def connect(root,exists):
    if exists:
        idle(); config_guard()
        if out('remote'): stop('Remote already configured. Register it instead.')
    login,env,gh=pick_account(); slug=slugcheck(input('Existing GitHub OWNER/REPO: ').strip()); d=verify_repo(slug,env,gh)
    url='https://github.com/'+slug+'.git'; refs=remote_refs(gh,env,url)
    if refs and (not exists or not head()):
        print('Remote has code; attaching this unrelated folder is unsafe. Clone into a NEW sibling project instead.')
        name=input('New sibling folder name (Enter = cancel): ').strip()
        if not name: return
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*',name) or name in {'.','..'}: stop('Invalid folder name.')
        dest=root.parent/name
        if dest.exists() or dest.is_symlink(): stop('Destination already exists. Never overwrite.')
        confirm('CLONE',f'Clone {slug} into NEW directory {dest}? Current folder stays untouched.')
        if boundary()!=(root,exists) or dest.exists() or dest.is_symlink(): stop('Folder state changed.')
        network(gh,env,'clone','--no-recurse-submodules','--',url,str(dest),capture=False)
        print(f'Clone created at {dest}. Open it in your IDE and register from its root.')
        return
    if refs:
        b=branch()
        if b not in refs: stop('No matching remote branch; compare histories manually.')
        sha=fetch_branch(gh,env,url,b,refs[b])
        if not ancestor(sha,head()) and not ancestor(head(),sha): stop('Histories diverged. No automatic attachment.')
    print(f'{root}\n{slug}\nAccount: {login}')
    confirm('CONNECT','Approve this exact local folder and existing remote?')
    if boundary()!=(root,exists): stop('Project boundary changed.')
    if not exists: git('init','-b','main')
    if out('remote'): stop('Remote now exists; no overwrite.')
    git('remote','add','origin',url)
    data=load(); data[str(root)]={'remote':url,'account':login,'repo_id':str(d['id'])}; save(data)
    print('Connected and registered. No push performed.')


def sync(root):
    idle(); clean(); b=branch(); h=head(); url,slug,login,env,gh,d=approved(root)
    sha=remote_refs(gh,env,url).get(b)
    if not sha: stop('Remote branch not found. Publish branch first.')
    fetch_branch(gh,env,url,b,sha)
    if not h or not ancestor(h,sha):
        if h: print('Local-only / remote-only commits:',out('rev-list','--left-right','--count',h+'...'+sha))
        stop('Cannot safely fast-forward. Use Compare with GitHub; merge or rebase only after review.')
    if h==sha: print('Already current.'); return
    git('--no-pager','log','--oneline',h+'..'+sha,capture=False)
    git('--no-pager','diff','--stat',h,sha,capture=False)
    confirm('PULL','Fast-forward current branch to reviewed remote commit?')
    clean()
    if head()!=h or branch()!=b: stop('Branch changed.')
    git('merge','--ff-only',sha,capture=False)


def local_branches():
    return out('for-each-ref','--format=%(refname:short)','refs/heads').splitlines()


def pick_local(prompt):
    bs=local_branches(); print('\n'.join(bs)); b=valid_branch(input(prompt).strip())
    if b not in bs: stop('Local branch not found.')
    return b


def branch_menu(root):
    advanced_guard(root)
    print('\n1 Create branch\n2 Switch local branch\n3 Download remote branch\n4 Compare branches\n5 Merge into current branch\n6 Delete merged local branch\n7 Publish current branch\n8 Combine latest GitHub branch into this branch\n0 Back')
    c=input('Choose: ').strip()
    if c=='1':
        clean(); base=pick_local('Base branch: '); b=valid_branch(input('New branch name: ').strip())
        confirm('CREATE',f'Create and switch to {b} from {base}?'); clean(); git('switch','--no-track','-c',b,'refs/heads/'+base,capture=False)
    elif c=='2':
        clean(); b=pick_local('Switch to: '); confirm('SWITCH',f'Switch to {b}?'); clean(); git('switch','--no-guess',b,capture=False)
    elif c=='3':
        clean(); url,slug,login,env,gh,d=approved(root); refs=remote_refs(gh,env,url); print('\n'.join(refs)); b=valid_branch(input('Remote branch: ').strip())
        if b not in refs or b in local_branches(): stop('Remote branch missing or local branch already exists.')
        sha=fetch_branch(gh,env,url,b,refs[b]); confirm('SWITCH',f'Create local {b} at {sha[:10]}?'); clean(); git('switch','--no-track','-c',b,sha,capture=False)
    elif c=='4':
        a=pick_local('First branch: '); b=pick_local('Second branch: ')
        git('--no-pager','log','--left-right','--oneline','refs/heads/'+a+'...refs/heads/'+b,capture=False); git('--no-pager','diff','--stat','refs/heads/'+a,'refs/heads/'+b,capture=False)
    elif c=='5':
        clean(); target=branch(); h=head(); b=pick_local('Merge FROM branch: ')
        if b==target: stop('Already on that branch.')
        sha=out('rev-parse','refs/heads/'+b)
        if ancestor(sha,h): print('Already merged.'); return
        if git('merge-base',h,sha,check=False).returncode: stop('Unrelated histories.')
        git('--no-pager','log','--oneline',h+'..'+sha,capture=False); git('--no-pager','diff','--stat',h,sha,capture=False)
        confirm('MERGE',f'Merge {b} INTO {target}, locally only?'); clean()
        if head()!=h or branch()!=target: stop('Branch changed.')
        checkpoint('before-merge')
        r=advanced_git('merge','--no-ff','--no-commit',sha,capture=False,check=False)
        if r.returncode: stop('Merge paused. Reopen GitAppho for guided conflict resolution. No push.')
        tree=review_index(); confirm('COMMIT','Finalize reviewed merge locally?')
        if out('write-tree')!=tree or head()!=h: stop('Merge changed.')
        git('commit','-m',f'Merge {b} into {target}',capture=False)
        print('Merge completed locally; push separately.')
    elif c=='6':
        clean(); b=pick_local('Delete local branch: ')
        if b in {'main','master',branch()} or not ancestor(out('rev-parse','refs/heads/'+b),head()): stop('Protected, active or unmerged branch.')
        confirm('DELETE '+b,'Delete this merged LOCAL branch only?'); git('branch','-d','--',b,capture=False)
    elif c=='7': push(root)
    elif c=='8': merge_remote(root)


def pr_menu(root):
    idle(); url,slug,login,env,gh,d=approved(root)
    print('1 Open pull request\n2 List pull requests\n3 Merge pull request\n0 Back'); c=input('Choose: ').strip()
    def g(*args,capture=True): return run([gh,'pr',*args,'--repo',slug],env=env,capture=capture)
    if c=='1':
        b=branch(); base=valid_branch(input('Target branch [main]: ').strip() or 'main'); refs=remote_refs(gh,env,url)
        if b==base or b not in refs or base not in refs or refs[b]!=head(): stop('Publish current branch first and verify target exists.')
        title=input('PR title: ').strip(); body=input('PR description: ').strip()
        if not title: stop('Title required.')
        confirm('PR',f'Open pull request {b} → {base} in {slug}?'); g('create','--head',b,'--base',base,'--title',title,'--body',body,capture=False)
    elif c=='2': g('list',capture=False)
    elif c=='3':
        g('list',capture=False); n=input('PR number: ').strip()
        if not n.isdigit(): stop('Invalid PR number.')
        info=json.loads(g('view',n,'--json','number,title,state,isDraft,headRefOid,headRefName,baseRefName,mergeStateStatus,reviewDecision,statusCheckRollup,isCrossRepository').stdout)
        print(json.dumps(info,indent=2))
        if info['state']!='OPEN' or info['isDraft'] or info['isCrossRepository'] or info['mergeStateStatus']!='CLEAN' or info['reviewDecision']=='CHANGES_REQUESTED' or info['reviewDecision']=='REVIEW_REQUIRED': stop('PR not ready. Resolve checks, conflicts or reviews on GitHub.')
        confirm('MERGE PR '+n,'Merge this exact GitHub PR? No admin bypass.'); g('merge',n,'--merge','--match-head-commit',info['headRefOid'],capture=False)


def recovery():
    if ongoing(): return conflict_menu(Path.cwd().resolve())
    states=ongoing(); print('Recovery state:',states or 'No operation in progress')
    if 'MERGE_HEAD' in states:
        confirm('ABORT','Abort the in-progress merge? Conflict edits will be discarded.'); git('merge','--abort',capture=False)
    elif 'REVERT_HEAD' in states:
        confirm('ABORT','Abort the in-progress revert? Conflict edits will be discarded.'); git('revert','--abort',capture=False)
    elif states: stop('Other operation in progress; use Git or IDE recovery manually.')
    else:
        clean(); h=head()
        if not h: stop('No commit to revert.')
        if len(out('rev-list','--parents','-n','1',h).split())!=2: stop('Root or merge commits require manual revert.')
        git('--no-pager','show','--stat',h,capture=False)
        confirm('REVERT','Create a new local commit reversing the latest commit?'); clean()
        if head()!=h: stop('HEAD changed.')
        checkpoint('before-revert'); advanced_git('revert','--no-edit',h,capture=False)
        print('Reverted locally. Push separately if appropriate.')


def status(root,exists):
    print(f'\nGitAppho v5 | {root}')
    if not exists: print('No independent Git repository.'); return
    print('Branch:',out('branch','--show-current') or '(detached)')
    ri=remote_info(); print('Remote:',ri[1] if ri else '(not connected)')
    row=load().get(str(root)); print('Registered account:',row.get('account') if row else '(not registered)')
    print('Operation in progress:',', '.join(ongoing()) or 'none')
    git('status','--short','--untracked-files=normal',capture=False)


# Advanced workflows. All mutations are local unless a verified network action says otherwise.
def advanced_guard(root, *, allow_operation=False):
    if boundary() != (root, True): stop('Open the exact independent project root.')
    config_guard()
    if not allow_operation: idle()
    # A repository may configure custom commands/drivers; avoid unattended execution.
    keys=out('config','--name-only','--list').lower().splitlines()
    if any(k.startswith(('merge.','diff.')) and k.endswith(('.driver','.command','.textconv')) for k in keys):
        stop('Custom merge or diff driver: use manual Git in this trusted project.')


def checkpoint(label):
    h=head()
    if not h: stop('Create a commit first.')
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    ref='refs/gitappho/checkpoints/'+stamp+'-'+label
    git('update-ref',ref,h,'0'*len(h))
    print('Recovery checkpoint:',ref)
    return ref


def conflict_paths():
    return paths('diff','--name-only','--diff-filter=U','-z')


def select_path(items, prompt='File number: '):
    if not items: stop('No matching files.')
    if len(items)>500: stop('Too many files; use manual review.')
    for i,p in enumerate(items,1): print(f'{i}. {p!r}')
    n=input(prompt).strip()
    if not n.isdigit() or not 1<=int(n)<=len(items): stop('Invalid file selection.')
    p=items[int(n)-1]; f=Path.cwd()/p
    if any(ord(c)<32 or ord(c)==127 for c in p) or f.resolve()!=f or Path.cwd() not in f.parents or f.is_symlink(): stop('Unsafe path.')
    return p


def advanced_git(*args, **kw):
    return git('-c','rerere.enabled=false','-c','rerere.autoupdate=false','-c','merge.autoStash=false','-c','rebase.autoStash=false','-c','rebase.updateRefs=false','-c','rebase.autoSquash=false',*args,**kw)


def conflict_menu(root):
    advanced_guard(root,allow_operation=True)
    states=ongoing(); files=conflict_paths()
    if 'index.lock' in states: stop('Git index locked. Close other Git operations; never delete the lock automatically.')
    kind=('rebase' if any(x in states for x in ('rebase-merge','rebase-apply')) else
          'merge' if 'MERGE_HEAD' in states else 'cherry-pick' if 'CHERRY_PICK_HEAD' in states else
          'revert' if 'REVERT_HEAD' in states else None)
    if 'BISECT_START' in states: return bisect_menu(root)
    if not kind and 'sequencer' in states: stop('Unrecognized sequencer operation; use manual Git recovery.')
    print('\nPaused operation:',kind or 'unmerged files (possibly stash restore)')
    for f in files: print('Conflict:',repr(f))
    print('1 Compare both conflict versions\n2 Mark a manually edited file resolved\n3 Continue operation / finish review\n4 Abort operation (if supported)\n0 Back')
    c=input('Choose: ').strip()
    if c=='1':
        p=select_path(files)
        print('Stage 2 and 3 are Git index sides; during rebase their meaning is reversed from a typical merge.')
        for i in (1,2,3):
            print(f'\n--- index stage {i} ---')
            r=git('show',f':{i}:{p}',check=False)
            if r.returncode: print('(absent)')
            elif len(r.stdout)>20000: print('(large file; review in IDE)')
            else: print(repr(r.stdout) if any(ord(k)<32 and k not in '\n\t\r' for k in r.stdout) else r.stdout)
    elif c=='2':
        p=select_path(files); sensitive([p]); f=root/p
        if f.exists():
            if not f.is_file(): stop('Not a regular file.')
            if f.stat().st_size>20*1024*1024: stop('Large conflict; review manually.')
            data=f.read_bytes()
            if b'\0' in data or any(re.match(rb'^(<<<<<<<|=======|>>>>>>>|\|\|\|\|\|\|\|)',l) for l in data.splitlines()): stop('Binary file or possible conflict markers remain; resolve manually.')
        print('Review in your IDE first. Missing file means the resolution is a deletion.')
        confirm('RESOLVE','Stage only '+repr(p)+' as resolved?')
        advanced_guard(root,allow_operation=True)
        if p not in conflict_paths(): stop('Conflict state changed.')
        git('--literal-pathspecs','add','--',p,capture=False)
    elif c=='3':
        if files: stop('Resolve all listed conflicts first.')
        if not kind: print('No sequencer to continue. Stash conflict resolution stays staged; inspect and commit normally.'); return
        if out('diff','--name-only'): stop('Unstaged tracked edits remain. Review and stage only intended changes.')
        tree=review_index(); confirm('CONTINUE',f'Continue {kind} locally with reviewed index? No push.')
        if conflict_paths() or out('write-tree')!=tree or ongoing()!=states: stop('Conflict state changed.')
        advanced_git('-c','core.editor=true',kind,'--continue',capture=False,check=False)
    elif c=='4':
        if not kind: stop('No safe automatic abort for stash conflicts. Stash is retained; review changes manually.')
        confirm('ABORT',f'Abort {kind}? Edits made during conflict resolution may be discarded.')
        if ongoing()!=states: stop('Operation changed.')
        advanced_git(kind,'--abort',capture=False)


def stash_entries():
    return [tuple(x.split('\t',2)) for x in out('stash','list','--format=%gd%x09%H%x09%gs').splitlines() if x]


def stash_menu(root):
    advanced_guard(root)
    print('1 Set tracked unfinished work aside\n2 Restore saved work (keep backup)\n3 Restore saved work and remove stash on success\n4 List saved work\n0 Back')
    c=input('Choose: ').strip()
    if c=='1':
        if not head() or not out('status','--porcelain','--untracked-files=no'): stop('No tracked work to stash.')
        git('status','--short',capture=False)
        label=input('Label [unfinished work]: ').strip() or 'unfinished work'
        confirm('STASH','Save tracked staged and unstaged changes locally? Untracked and ignored files stay untouched.')
        advanced_guard(root); advanced_git('stash','push','-m','GitAppho: '+label,capture=False)
    elif c in ('2','3','4'):
        entries=stash_entries()
        for i,(ref,sha,msg) in enumerate(entries,1): print(i,ref,sha[:10],repr(msg))
        if c=='4' or not entries: return
        clean(); n=input('Saved work number: ').strip()
        if not n.isdigit() or not 1<=int(n)<=len(entries): stop('Invalid stash.')
        ref,sha,msg=entries[int(n)-1]
        git('--no-pager','stash','show','--stat',ref,capture=False)
        confirm('RESTORE','Apply saved work to current branch? The stash survives any conflict.')
        advanced_guard(root); clean()
        if not any(x[:2]==(ref,sha) for x in stash_entries()): stop('Stash changed.')
        r=advanced_git('stash','apply','--index',sha,capture=False,check=False)
        if r.returncode:
            print('Restore paused or failed. Original stash is retained. Review status; resolve any conflicts using the recovery menu.'); return
        if c=='3':
            if not any(x[:2]==(ref,sha) for x in stash_entries()): stop('Applied successfully, but stash list changed; backup retained.')
            # Pin the stash object before dropping its list entry.
            stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            backup='refs/gitappho/checkpoints/'+stamp+'-stash'
            git('update-ref',backup,sha,'0'*len(sha)); git('stash','drop',ref,capture=False)
            print('Restored; recovery reference retained:',backup)
        else: print('Restored; stash retained.')


def choose_commit(prompt='Commit hash: '):
    git('--no-pager','log','--exclude=refs/gitappho/*','--all','--oneline','--max-count=25',capture=False,check=False)
    s=input(prompt).strip()
    if not re.fullmatch(r'[a-fA-F0-9]{7,64}',s): stop('Enter a displayed commit hash (at least 7 hex characters).')
    return out('rev-parse','--verify',s+'^{commit}')


def unpublished(root, base, h):
    # Refuse rewrite on protected branches and any commit reachable from currently visible remote refs.
    if branch() in ('main','master'): stop('History rewriting of main/master is blocked. Use revert or merge.')
    if not ancestor(base,h): stop('Rewrite base is not an ancestor.')
    commits=out('rev-list',base+'..'+h).splitlines()
    if not commits: stop('No commits to rewrite.')
    if len(commits)>100 or out('rev-list','--merges',base+'..'+h): stop('Large or merge-containing history requires manual review.')
    remotes=out('remote').splitlines()
    tips=out('for-each-ref','--format=%(objectname)','refs/remotes','refs/tags').splitlines()
    if remotes:
        if remotes!=['origin']: stop('Multiple or unsupported remotes; cannot verify unpublished history.')
        url,slug,login,env,gh,d=approved(root)
        result=network(gh,env,'ls-remote','--refs',url).stdout.splitlines()
        if len(result)>100: stop('Too many remote refs for conservative rewrite verification.')
        for line in result:
            sha,ref=line.split('\t',1)
            if not re.fullmatch(r'[a-f0-9]{40,64}',sha) or not ref.startswith(('refs/heads/','refs/tags/')): stop('Unexpected remote ref.')
            if git('cat-file','-e',sha,check=False).returncode:
                network(gh,env,'fetch','--no-tags','--no-recurse-submodules',url,ref)
                if out('rev-parse','FETCH_HEAD')!=sha: stop('Remote changed during verification.')
            tips.append(sha)
    for tip in set(tips):
        peeled=git('rev-parse','--verify',tip+'^{commit}',check=False)
        if peeled.returncode: continue
        for sha in commits:
            if ancestor(sha,peeled.stdout.strip()): stop('A commit to rewrite is reachable from a remote-tracking ref or tag. Use merge/revert instead.')
    # This proves only currently visible refs, not whether someone previously copied the commits.
    return commits


def rewrite_menu(root):
    advanced_guard(root); clean(); h=head(); b=branch()
    if not h: stop('No commit yet.')
    print('1 Replay my private feature on another local branch (rebase)\n2 Undo last unpublished commit, keep changes staged\n3 Correct last unpublished commit message\n4 Combine recent unpublished commits (squash)\n0 Back')
    c=input('Choose: ').strip()
    if c not in ('1','2','3','4'): return
    if c=='1':
        name=pick_local('New base branch: ')
        if name==b: stop('Choose another branch.')
        dest=out('rev-parse','refs/heads/'+name)
        bases=out('merge-base','--all',h,dest).splitlines()
        if len(bases)!=1: stop('Unrelated or ambiguous history.')
        base=bases[0]
        if base==dest: print('Already based on that commit.'); return
    else:
        n=1
        if c=='4':
            raw=input('Number of last commits to combine (2–20): ').strip()
            if not raw.isdigit() or not 2<=int(raw)<=20: stop('Invalid number.')
            n=int(raw)
        base=out('rev-parse','--verify',f'HEAD~{n}')
    commits=unpublished(root,base,h)
    git('--no-pager','log','--oneline',base+'..'+h,capture=False)
    print('Only use on private work nobody else depends on. Current refs checked; previous copies cannot be ruled out.')
    msg=None
    if c in ('3','4'):
        msg=input('New commit message: ').strip()
        if not msg: stop('Cancelled.')
    confirm('REWRITE','Create a recovery ref and rewrite only these local commits? No force push.')
    advanced_guard(root); clean()
    if head()!=h or branch()!=b or unpublished(root,base,h)!=commits: stop('History changed.')
    checkpoint('before-rewrite')
    if c=='1':
        advanced_git('rebase','--no-autostash','--no-update-refs','--no-fork-point','--no-rebase-merges','--no-autosquash','--reapply-cherry-picks','--empty=ask',dest,capture=False,check=False)
        if ongoing(): print('Rebase paused. Reopen GitAppho for guided conflict recovery.')
    elif c=='2': git('reset','--soft',base,capture=False); print('Commit removed locally; changes remain staged.')
    elif c=='3': advanced_git('commit','--amend','-m',msg,capture=False)
    else:
        git('reset','--soft',base,capture=False); advanced_git('commit','-m',msg,capture=False)
        print('Commits combined locally. Recovery ref preserves original history.')


def specific_changes(root):
    advanced_guard(root)
    print('1 Bring a specific commit into current branch\n2 Revert a specific ordinary commit\n3 Restore an accidentally deleted tracked file from HEAD\n4 Stop tracking a file, keep local copy\n5 Show who changed a file (blame)\n0 Back')
    c=input('Choose: ').strip()
    if c in ('1','2'):
        clean(); h=head(); b=branch(); sha=choose_commit()
        if len(out('rev-list','--parents','-n','1',sha).split())!=2: stop('Root/merge commits require manual handling.')
        git('--no-pager','show','--stat',sha,capture=False)
        action='cherry-pick' if c=='1' else 'revert'
        confirm('APPLY',f'{action} {sha[:12]} on {b} locally?')
        advanced_guard(root); clean()
        if head()!=h or branch()!=b: stop('Branch changed.')
        checkpoint('before-'+action); advanced_git(action,'--no-edit',sha,capture=False,check=False)
        if ongoing(): print('Operation paused. Reopen GitAppho for conflict recovery.')
    elif c=='3':
        p=select_path(paths('diff','--name-only','--diff-filter=D','-z'))
        if (root/p).exists() or p in paths('diff','--cached','--name-only','-z'): stop('Only unstaged deletions supported; review staged changes manually.')
        sensitive([p]); confirm('RESTORE','Restore '+repr(p)+' from HEAD?')
        if (root/p).exists(): stop('File reappeared.')
        git('--literal-pathspecs','restore','--source=HEAD','--worktree','--',p,capture=False)
    elif c=='4':
        p=select_path(paths('ls-files','-z'))
        f=root/p
        if any(x in p for x in '*?[]') or p.startswith(':'): stop('Special path requires manual review.')
        if not f.is_file() or git('check-ignore','--no-index','-q','--',p,check=False).returncode: stop('Add an appropriate .gitignore rule first. File must exist and be ignored.')
        confirm('UNTRACK','Stage removal of '+repr(p)+' while keeping your local file? This does not remove history.')
        if not f.is_file() or git('check-ignore','--no-index','-q','--',p,check=False).returncode: stop('File or ignore rule changed.')
        git('--literal-pathspecs','rm','--cached','--',p,capture=False)
    elif c=='5':
        p=select_path(paths('ls-files','-z')); git('--no-pager','blame','--',p,capture=False)


def checkpoints_menu(root):
    advanced_guard(root)
    rows=out('for-each-ref','--sort=-refname','--format=%(refname)%09%(objectname)%09%(subject)','refs/gitappho/checkpoints').splitlines()
    print('\nLocal recovery checkpoints (commits, not working-tree snapshots):')
    for row in rows[:50]: print(repr(row))
    git('--no-pager','reflog','--date=local','-n','30',capture=False)
    if input('Create a NEW rescue branch from a checkpoint or reflog commit? [y/N]: ').lower()!='y': return
    sha=choose_commit('Recovery commit hash: '); b=valid_branch(input('New rescue branch name: ').strip())
    confirm('RESCUE',f'Create branch {b} at {sha[:12]} without switching or overwriting anything?')
    git('branch','--no-track',b,sha,capture=False)


def bisect_menu(root):
    advanced_guard(root,allow_operation=True)
    active='BISECT_START' in ongoing()
    if not active:
        idle(); clean(); bad=head(); branch()
        if not bad: stop('No commits.')
        good=choose_commit('Known working commit hash: ')
        if good==bad or not ancestor(good,bad): stop('Good must precede current bad commit.')
        confirm('BISECT','Start local bug search? Git will check out historical commits for manual testing.')
        clean(); checkpoint('before-bisect'); advanced_git('bisect','start',bad,good,capture=False)
    else:
        print('Test current checked-out commit.\n1 Works (good)\n2 Broken (bad)\n3 Cannot test (skip)\n4 Show search log\n5 Finish / return to original branch\n0 Back')
        c=input('Choose: ').strip()
        if c in ('1','2','3','5'):
            clean(); word={'1':'good','2':'bad','3':'skip','5':'reset'}[c]
            confirm(word.upper(),'Record result or finish the local bug search?'); advanced_git('bisect',word,capture=False)
        elif c=='4': git('bisect','log',capture=False)


def scan_history(span):
    scanner=shutil.which('gitleaks')
    if not scanner: stop('Secret scanner required for publishing. Install Gitleaks 8.x: brew install gitleaks')
    if not re.fullmatch(r'[0-9a-f]{40,64}(?:\.\.[0-9a-f]{40,64})?',span): stop('Invalid scan range.')
    with tempfile.TemporaryDirectory(prefix='gitappho-scan-') as temp:
        cfg=Path(temp)/'rules.toml'; cfg.write_text('[extend]\nuseDefault = true\n')
        ignore=Path(temp)/'.gitleaksignore'; ignore.write_text('')
        env={k:v for k,v in os.environ.items() if not k.startswith('GITLEAKS_')}
        result=run([scanner,'git','--config',str(cfg),'--gitleaks-ignore-path',str(ignore),'--ignore-gitleaks-allow','--redact=100','--no-banner','--no-color','--log-opts='+span+' --full-history -m',str(Path.cwd())],env=env,check=False)
        if result.returncode: stop('Gitleaks reported findings or failed. No upload. Run a local redacted scan to investigate.')
    print('Outgoing history passed Gitleaks rules (not a guarantee of no secrets).')


def github_extras(root):
    advanced_guard(root); url,slug,login,env,gh,d=approved(root)
    print('1 List issues\n2 List CI workflow runs\n3 View pull request checks\n4 List releases\n5 Prepare a draft release on an existing published commit\n0 Back')
    c=input('Choose: ').strip()
    options={'1':['issue','list'],'2':['run','list'],'4':['release','list']}
    if c in options: run([gh,*options[c],'--repo',slug],env=env,capture=False)
    elif c=='3':
        n=input('PR number: ').strip()
        if not n.isdigit(): stop('Invalid PR number.')
        run([gh,'pr','checks',n,'--repo',slug],env=env,capture=False,check=False)
    elif c=='5':
        h=head(); b=branch()
        if remote_refs(gh,env,url).get(b)!=h or not h: stop('Publish reviewed current branch first.')
        tag=input('Existing published tag (e.g. v5.0.0): ').strip()
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*',tag): stop('Invalid tag.')
        r=network(gh,env,'ls-remote','--tags',url,'refs/tags/'+tag,'refs/tags/'+tag+'^{}').stdout.splitlines()
        ids={line.split('\t')[1]:line.split('\t')[0] for line in r}
        if ids.get('refs/tags/'+tag+'^{}',ids.get('refs/tags/'+tag))!=h: stop('Tag does not exist at this exact published commit. Create tags manually for now.')
        confirm('DRAFT','Create draft GitHub release for '+tag+'? Nothing published publicly.')
        run([gh,'release','create',tag,'--verify-tag','--draft','--title',tag,'--notes','Review release notes before publication.','--repo',slug],env=env,capture=False)


def merge_remote(root):
    advanced_guard(root); clean(); h=head(); b=branch()
    url,slug,login,env,gh,d=approved(root)
    refs=remote_refs(gh,env,url)
    for name in sorted(refs): print(repr(name))
    source=valid_branch(input('Bring changes FROM GitHub branch: ').strip())
    if source not in refs or not h: stop('Remote branch or local commit missing.')
    sha=fetch_branch(gh,env,url,source,refs[source])
    if ancestor(sha,h): print('Already contains these changes.'); return
    if git('merge-base',h,sha,check=False).returncode: stop('Unrelated histories.')
    git('--no-pager','log','--oneline',h+'..'+sha,capture=False)
    git('--no-pager','diff','--stat',h,sha,capture=False)
    confirm('MERGE',f'Combine GitHub {source} into local {b}? No automatic push.')
    advanced_guard(root); clean()
    if head()!=h or branch()!=b or remote_refs(gh,env,url).get(source)!=sha: stop('History changed.')
    checkpoint('before-remote-merge')
    result=advanced_git('merge','--no-ff','--no-commit',sha,capture=False,check=False)
    if result.returncode and not ongoing(): stop('Merge failed; review Git status.')
    print('Review merge in GitAppho recovery; choose Continue after resolving any conflicts.')


def advanced_menu(root):
    advanced_guard(root)
    print('\n1 Set aside / restore unfinished work (stash)\n2 Replay or tidy private commits (rebase / amend / squash / undo)\n3 Bring, revert, restore or inspect specific changes\n4 Recovery checkpoints and lost commits\n5 Find when a bug started (bisect)\n6 GitHub issues, CI and draft releases\n7 Scan current commit history for secrets\n0 Back')
    c=input('Choose: ').strip()
    if c=='1': stash_menu(root)
    elif c=='2': rewrite_menu(root)
    elif c=='3': specific_changes(root)
    elif c=='4': checkpoints_menu(root)
    elif c=='5': bisect_menu(root)
    elif c=='6': github_extras(root)
    elif c=='7':
        h=head()
        if not h: stop('No commit yet.')
        scan_history(h)



def main():
    p=argparse.ArgumentParser(description='GitAppho v5 — one menu, guarded Git workflows')
    g=p.add_mutually_exclusive_group()
    p.add_argument('--version',action='version',version='GitAppho 5.0.0')
    for x in ('login','accounts','projects','status','doctor','register','publish','connect','advanced'): g.add_argument('--'+x,action='store_true')
    g.add_argument('--account',metavar='USERNAME')
    a=p.parse_args()
    if a.login: login_action(); return
    if a.accounts: run([gh_path(),'auth','status','--hostname','github.com'],env=gh_env(),capture=False,check=False); return
    if a.projects:
        for path,row in load().items(): print(path, row.get('account'),row.get('remote'))
        return
    if a.doctor:
        print('Python:',sys.version.split()[0]); print('Git:',out('--version')); print('GitHub CLI:',shutil.which('gh') or 'missing (brew install gh)'); print('Gitleaks:',shutil.which('gitleaks') or 'missing (brew install gitleaks)'); print('Registry:',REGISTRY); return
    root,exists=boundary()
    if exists: config_guard()
    if a.status: status(root,exists); return
    if a.advanced:
        if not exists: stop('Open a Git repository first.')
        if ongoing(): conflict_menu(root)
        else: advanced_menu(root)
        return
    if a.publish: publish(root,exists); return
    if a.connect: connect(root,exists); return
    if a.register or a.account:
        if not exists or not remote_info(): stop('No connected independent repo. Use --publish or --connect.')
        register(root,*remote_info(),a.account); return
    while True:
        if boundary()[0]!=root: stop('Project changed.')
        exists=(root/'.git').is_dir(); status(root,exists)
        if exists and ongoing():
            print('1 Resolve conflicts / resume or cancel operation\n0 Exit'); c=input('Choose: ').strip()
            if c=='1': conflict_menu(root)
            return
        if not exists or not remote_info():
            print('1 Publish new project to GitHub\n2 Connect existing GitHub repository\n3 Sign in to GitHub\n4 Local advanced tools (requires local repo)\n0 Exit')
            c=input('Choose: ').strip()
            if c=='1': publish(root,exists); return
            elif c=='2': connect(root,exists)
            elif c=='3': login_action()
            elif c=='4' and exists: advanced_menu(root)
            else: return
        else:
            row=load().get(str(root)); ri=remote_info()
            if not row or row.get('remote')!=ri[0]:
                print('1 Register this project\n2 Sign in to GitHub\n0 Exit'); c=input('Choose: ').strip()
                if c=='1':
                    user=input('GitHub username (Enter = active): ').strip(); register(root,*ri,user or None)
                elif c=='2': login_action()
                else: return
            else:
                print('1 Save and publish my changes\n2 Push existing commits\n3 Get latest changes (fast-forward only)\n4 Manage branches\n5 Pull requests\n6 Change account\n7 Recover / revert\n8 Save local commit only\n9 Compare with GitHub\n10 Advanced Git & recovery tools\n0 Exit')
                c=input('Choose: ').strip()
                if c=='1': approved(root); stage_commit(); push(root); return
                elif c=='2': push(root); return
                elif c=='3': sync(root)
                elif c=='4': branch_menu(root)
                elif c=='5': pr_menu(root)
                elif c=='6':
                    user=input('GitHub username (Enter = active): ').strip(); register(root,*ri,user or None)
                elif c=='7': recovery()
                elif c=='8': stage_commit()
                elif c=='9':
                    url,slug,login,env,gh,d=approved(root); b=branch(); h=head(); sha=remote_refs(gh,env,url).get(b)
                    if not sha: print('Current branch has not been published.')
                    elif not h: print('No local commit yet.')
                    else:
                        fetch_branch(gh,env,url,b,sha)
                        print('Local-only / remote-only commits:',out('rev-list','--left-right','--count',h+'...'+sha))
                        git('--no-pager','log','--left-right','--oneline','--max-count=30',h+'...'+sha,capture=False)
                elif c=='10': advanced_menu(root)
                else: return

def cli():
    try: main()
    except (KeyboardInterrupt,EOFError): stop('Cancelled. Inspect git status before retrying.')
    except (OSError,ValueError,KeyError,TypeError,AttributeError): stop('Unexpected local or GitHub response. No further operations performed; inspect git status.')


if __name__=='__main__': cli()
