"""Studio account workflows. Credentials remain managed by gh, not this module."""
import json, re, subprocess, os, shutil, sys, time, signal, selectors, pwd
from pathlib import Path

GRAPH = {
    'inspect': ('local','unregistered','registered'),
    'local': ('exit','connect'), 'connect': ('unregistered','exit'),
    'unregistered': ('select','exit'), 'registered': ('select','verify','exit'),
    'select': ('dependency','verify','exit'),
    'dependency': ('verify','install-gh','exit'),
    'install-gh': ('verify','exit'),
    'external-login': ('verify','exit'),
    'verify': ('verified','credentials','sso','permission','missing','network','unknown'),
    'verified': ('bind','publish','exit'), 'bind': ('registered','exit'),
    'publish': ('exit','credentials','sso','permission','missing','network','unknown'),
    **{s: ('verify','select','exit') for s in ('sso','permission','missing','network','unknown')},
    'credentials': ('external-login','select','exit'),
    'exit': (),
}
MESSAGES = {
 'credentials': 'Saved credential unavailable or rejected. Check the selected account; renew only if needed.',
 'sso': 'Organisation SSO or OAuth approval may be required. Authorize GitHub CLI in your browser or contact your organisation administrator.',
 'permission': 'GitHub denied the request. Check repository permissions, organisation restrictions or API rate limits; do not automatically log in again.',
 'missing': 'Repository not found or not visible to this account. Check owner/name and private repository access.',
 'network': 'Network or service failure. Keep local work; retry verification later. No automatic login or upload retry.',
 'keychain': 'GitHub CLI reported a credential-store problem. Cancel any unexpected macOS password or Keychain prompt. No retry or storage change will be attempted by GitAppho.',
 'unknown': 'GitHub request failed for an unclassified reason. Inspect the connection before retrying.',
}

def classify(stderr, *, token=False):
    s=(stderr or '').casefold()
    if any(x in s for x in ('keychain','keyring','credential store','insecure storage','plain text','plaintext','secure storage','security: sec')):return 'keychain'
    if 'saml' in s or 'single sign-on' in s or 'sso' in s or 'oauth app access restriction' in s:return 'sso'
    if re.search(r'\b(429|50[0234])\b',s) or any(x in s for x in ('timed out','timeout','connection refused','connection reset','no such host','could not resolve','network is unreachable','tls handshake','dial tcp','rate limit','eof')):return 'network'
    if re.search(r'\b401\b',s) or any(x in s for x in ('bad credentials','not logged','no oauth token','not authenticated','authentication token not found','no token found','no account found','no accounts found','not logged into','not logged in to any github hosts')):return 'credentials'
    if re.search(r'\b403\b',s) or 'forbidden' in s:return 'permission'
    if re.search(r'\b404\b',s) or 'not found' in s:return 'missing'
    return 'unknown'

def isolated_macos_profile():
    # Changing HOME/GH_CONFIG_DIR does not create a separate macOS keychain.
    # Fail closed before invoking gh in the previously provided FirstRun lab.
    if sys.platform != 'darwin':return False
    try:
        actual=Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()
        home=Path.home().resolve()
        custom=os.environ.get('GH_CONFIG_DIR','')
        if home!=actual:return True
        if custom and any(x.startswith('GitAppho-FirstRun.') for x in Path(custom).resolve().parts):return True
        xdg=os.environ.get('XDG_CONFIG_HOME','')
        return bool(xdg and any(x.startswith('GitAppho-FirstRun.') for x in Path(xdg).resolve().parts))
    except (OSError,ValueError,KeyError,RuntimeError):return True


def profile_allowed(core):
    if not isolated_macos_profile():return True
    core.print('Live GitHub authentication is disabled in this artificial first-run profile. macOS Keychain is shared across HOME and GH_CONFIG_DIR. Your normal account is not being changed. Use your normal macOS session, or a separate macOS user / VM for a truly fresh live login. Local Git remains available.')
    return False


def list_saved(core):
    if not profile_allowed(core):return []
    # Only explicit account management needs a full account listing.
    gh=shutil.which('gh')
    if not gh:return []
    env=core.gh_env();env['GH_PROMPT_DISABLED']='1'
    for flags in (['--json','hosts','--no-refresh'],['--json','hosts'],[]):
        try:
            p=subprocess.run([gh,'auth','status','--hostname','github.com',*flags],env=env,capture_output=True,text=True,timeout=15,stdin=subprocess.DEVNULL)
            if flags:
                rows=json.loads(p.stdout).get('hosts',{}).get('github.com',[])
                if isinstance(rows,list):
                    return sorted({r['login'] for r in rows if isinstance(r,dict) and isinstance(r.get('login'),str) and re.fullmatch(r'[A-Za-z0-9-]+',r['login'])},key=str.casefold)
            else:
                return sorted(set(re.findall(r'Logged in to github\.com (?:account|as) ([A-Za-z0-9-]+)',p.stdout+'\n'+p.stderr)),key=str.casefold)
        except subprocess.TimeoutExpired:return []
        except (OSError,ValueError,TypeError,AttributeError):continue
    return []


def _stop_child(child):
    # Only our own subprocess group; never kill unrelated Git or shell processes.
    if child.poll() is None:
        try:os.killpg(child.pid,signal.SIGTERM)
        except ProcessLookupError:pass
        try:child.wait(timeout=1)
        except subprocess.TimeoutExpired:
            try:os.killpg(child.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            child.wait()


def _browser(core):
    # Open only the official GitHub device page, not URLs from subprocess output.
    opener='/usr/bin/open' if sys.platform=='darwin' else shutil.which('xdg-open')
    if opener:
        try:
            subprocess.Popen([opener,'https://github.com/login/device'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
            core.print('Opening browser. If it does not appear, visit https://github.com/login/device.')
            return
        except OSError:pass
    core.print('Open https://github.com/login/device in your browser.')


def _device_code(output):
    # gh <= older releases: "First copy your one-time code: ABCD-EFGH"
    # gh with automatic clipboard: "One-time code (ABCD-EFGH) copied to clipboard"
    clean=re.sub(r'\x1b\[[0-9;?]*[ -/]*[@-~]','',output)
    m=re.search(r'(?:one-time code|user code)\s*(?::\s*|\(\s*)([A-Z0-9]{4}-[A-Z0-9]{4})\b',clean,re.I)
    return m.group(1).upper() if m else None


def _job(core,args,env,*,label,limit,device=False,code_limit=60):
    # stdout and stderr are consumed in bounded chunks. Never forward raw auth output.
    # Only the one-time USER code is rendered, never OAuth access/device tokens.
    core.print(('Requesting a GitHub device code' if device else label)+'… Ctrl+C cancels.')
    start=time.monotonic();last=start;tail='';code=None
    try:
        with subprocess.Popen(args,env=env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,start_new_session=True) as child:
            try:
                with selectors.DefaultSelector() as sel:
                    sel.register(child.stdout,selectors.EVENT_READ)
                    while True:
                        now=time.monotonic()
                        if device and code is None and now-start>=code_limit:
                            core.print('GitHub did not provide a recognised device code within '+str(code_limit)+'s. Sign-in stopped; check network or GitHub CLI version. No automatic retry.')
                            return False
                        if now-start>=limit:
                            core.print(label+' timed out. No automatic retry.');return False
                        if now-last>=15:
                            core.print(('Waiting for browser approval' if device and code else 'Requesting GitHub device code' if device else label)+f' ({int(now-start)}s)…');last=now
                        events=sel.select(timeout=min(1,max(0,limit-(now-start))))
                        if not events:continue
                        data=os.read(child.stdout.fileno(),4096)
                        if not data:break
                        tail=(tail+data.decode('utf-8','replace'))[-16000:]
                        if device and code is None:
                            # Disable color in env; tolerate a code split across output chunks.
                            code=_device_code(tail)
                            if code:
                                # The native prompt keeps the code visible until the user returns.
                                # gh continues polling in its own process during the dialog.
                                core.print('Enter the one-time code in the official GitHub browser page. Do not share it. If macOS asks to create/reset a keychain or replace an unrelated password, cancel.')
                                _browser(core)
                                if core.menu('GITHUB DEVICE CODE: '+code,[('continue','I have authorised in GitHub — continue'),('cancel','Cancel sign-in')],recommended='continue')!='continue':
                                    core.print('Sign-in interrupted. No automatic retry. Browser approval, if already given, may have saved a GitHub CLI credential.');return False
                                core.print('Checking browser authorization…')
                    remaining=max(0.1,limit-(time.monotonic()-start))
                    try:rc=child.wait(timeout=remaining)
                    except subprocess.TimeoutExpired:
                        core.print(label+' timed out. No automatic retry.');return False
                    if device and classify(tail)=='keychain':
                        core.print(MESSAGES['keychain']+' GitHub CLI may already have saved a credential; inspect its storage before continuing.');return False
                    if rc:
                        core.print(label+' failed. '+MESSAGES[classify(tail)] if device else label+' failed (exit '+str(rc)+'). Check Homebrew permissions or network.')
                        return False
                    core.print(label+' completed.');return True
            finally:_stop_child(child)
    except OSError:
        core.print(label+' could not start. Check the dependency installation.');return False


def ensure_gh(core):
    if not profile_allowed(core):return None
    gh=shutil.which('gh')
    if gh:return gh
    if sys.platform=='darwin':
        for candidate in ('/opt/homebrew/bin/gh','/usr/local/bin/gh'):
            if os.path.isfile(candidate) and os.access(candidate,os.X_OK):
                os.environ['PATH']=os.path.dirname(candidate)+os.pathsep+os.environ.get('PATH','')
                return candidate
    if sys.platform!='darwin':
        core.print('GitHub CLI is missing. Automatic installation is currently supported on macOS with Homebrew.');return None
    brew=shutil.which('brew') or next((p for p in ('/opt/homebrew/bin/brew','/usr/local/bin/brew') if os.path.isfile(p) and os.access(p,os.X_OK)),None)
    if not brew:
        core.print('Homebrew is missing too. Install it from https://brew.sh/ and retry. No remote installer scripts are run automatically.');return None
    if core.menu('GitHub CLI is required for GitHub operations',[('install','Install GitHub CLI now (Homebrew)'),('offline','Not now — keep working locally')])!='install':return None
    env=dict(os.environ,HOMEBREW_NO_ENV_HINTS='1',HOMEBREW_NO_AUTO_UPDATE='1',NONINTERACTIVE='1')
    if not _job(core,[brew,'install','gh'],env,label='Installing GitHub CLI',limit=600):return None
    # Homebrew and gh normally share bin; update this worker PATH only.
    for directory in (os.path.dirname(brew),'/opt/homebrew/bin','/usr/local/bin'):
        if directory not in os.environ.get('PATH','').split(os.pathsep):os.environ['PATH']=directory+os.pathsep+os.environ.get('PATH','')
    gh=shutil.which('gh')
    if not gh:core.print('GitHub CLI installation completed but gh is not on PATH. Reopen Studio and retry.')
    return gh


def browser_login(core):
    gh=ensure_gh(core)
    if not gh:return False
    if core.menu('GitHub CLI manages its own credentials. macOS may ask to allow access to its GitHub token. Never create or reset a keychain for this app.', [('continue','Continue with official GitHub sign-in'),('cancel','Cancel — no credential changes')])!='continue':return False
    # --web selects the official device flow; noninteractive stdin means gh prints
    # its code and polls without waiting for Enter. GitAppho opens the fixed URL.
    env=core.gh_env();env.pop('GH_FORCE_TTY',None)
    env.update(GH_PROMPT_DISABLED='1',NO_COLOR='1',CLICOLOR='0',CLICOLOR_FORCE='0',TERM='dumb')
    return _job(core,[gh,'auth','login','--hostname','github.com','--web','--git-protocol','https'],env,label='GitHub sign-in',limit=600,device=True)

def install(core):
    """Attach only in Studio; no on-disk core or credential mutations."""
    if getattr(core,'_studio_accounts',False):return
    core._studio_accounts=True
    original_run=core.run
    original_save=core.intent_save
    original_identity=core.identity
    original_stage=core.stage_commit
    original_publish=core.publish
    def run(args,*,env=None,capture=True,check=True):
        is_gh=core.Path(args[0]).name=='gh'
        if is_gh and not profile_allowed(core):core.stop('Live GitHub access blocked in isolated macOS profile.')
        relevant=is_gh and capture and (args[1:2]==['api'] or args[1:3]==['auth','token'])
        if not relevant:return original_run(args,env=env,capture=capture,check=check)
        try:p=original_run(args,env=env,capture=capture,check=False)
        except SystemExit as e:
            if 'timed out' in str(e):
                core.print(MESSAGES['network']);core.print('Search Accounts & Organisations for connection recovery.')
            raise
        if p.returncode and check:
            state=classify(p.stderr,token=args[1:3]==['auth','token'])
            core.stop(MESSAGES[state]+' Search Accounts & Organisations for connection recovery.')
        return p
    def login_now():
        if not browser_login(core):
            core.print('Sign-in did not complete. Return to your workspace or choose Login again. No repository was created by sign-in.')
            return None
        # One real verification after gh completes, not repeated account polling.
        try:
            result=original_identity()
        except SystemExit as e:
            core.print(str(e));core.print('GitHub CLI finished sign-in, but verification failed. Retry verification later; do not sign in repeatedly.')
            return None
        core.print('Signed in as '+result[0]+'.')
        return result
    def choose_identity():
        if not profile_allowed(core):core.stop('Live login is disabled in this test profile; GitHub CLI is not necessarily missing. Use the simulated onboarding lab or a separate macOS user. Local work remains available.')
        if not ensure_gh(core):core.stop('GitHub CLI unavailable or installation declined. Local work is still available.')
        try:
            result=original_identity()
            core.print('Using saved GitHub account: '+result[0]+'.')
            return result
        except SystemExit as e:
            # A transport/permission error is not evidence of a missing account.
            if MESSAGES['credentials'] not in str(e):raise
            core.print('No usable saved GitHub login. Connect once to continue.')
        if core.menu('Connect your GitHub account',[('login','Continue with GitHub — open browser'),('offline','Not now — return to workspace')],recommended='login')!='login':core.stop('Sign-in cancelled. No repository created.')
        result=login_now()
        if result is None:core.stop('Sign-in incomplete. No repository created. Retry when ready.')
        return result
    def identity(account=None):
        # Keep a pinned account pinned. Only explicit approval can renew it.
        try:return original_identity(account)
        except SystemExit as e:
            if not account or MESSAGES['credentials'] not in str(e):raise
            core.print('The saved login for '+account+' is unavailable. Your project binding is unchanged.')
            if core.menu('Reconnect '+account,[('login','Sign in to GitHub in browser'),('back','Not now — retain local work')])!='login':raise
            result=login_now()
            if result is None:core.stop('Sign-in incomplete; local work remains.')
            if result[0].casefold()!=account.casefold():core.stop('Signed in as a different account. Choose the account for this project explicitly in Accounts & Organisations.')
            return result
    def ensure_registered(root):
        ri=core.remote_info()
        if not ri:core.stop('Connect or publish the repository first.')
        if core.load().get(str(root),{}).get('remote')!=ri[0]:
            core.print('Existing repository detected. Verify the account and destination once.')
            result=choose_identity()
            core.register(root,*ri,result[0])
    def stage_with_identity():
        # Git commit author configuration is independent of GitHub authentication.
        if core.git('var','GIT_AUTHOR_IDENT',check=False).returncode or core.git('var','GIT_COMMITTER_IDENT',check=False).returncode:
            root,exists=core.boundary()
            if not exists:core.stop('Initialise a local repository first.')
            core.print('First commit setup: Git needs a name and email. These are commit metadata, not GitHub credentials. Use your GitHub no-reply email if you prefer privacy.')
            name=core.input('Commit author name: ').strip(); email=core.input('Commit author email: ').strip()
            if not name or len(name)>200 or any(c in name for c in '<>') or not re.fullmatch(r'[^\s<>@]+@[^\s<>@]+',email) or len(email)>254:core.stop('Invalid author name or email. Retry the save action.')
            core.confirm('CONFIGURE','Save this author name and email in this repository only? Commit metadata can become public.')
            if core.boundary()!=(root,True):core.stop('Project changed.')
            core.git('config','--local','user.name',name);core.git('config','--local','user.email',email)
            if core.git('var','GIT_AUTHOR_IDENT',check=False).returncode or core.git('var','GIT_COMMITTER_IDENT',check=False).returncode:core.stop('Commit identity still unavailable. Inspect Git configuration.')
        return original_stage()
    def select_account(root):
        ri=core.remote_info()
        if not ri:core.stop('Connect an existing repository first. Search Connect in Studio.')
        if not ensure_gh(core):return
        names=list_saved(core)
        choices=[('account:'+n,n) for n in names]+[('active','Use the active GitHub CLI account'),('login','Add or renew an account in browser'),('manual','Enter a saved GitHub username')]
        c=core.menu('Choose the identity for this project',choices)
        if c=='login':
            result=login_now()
            if result is None:return
            user=result[0]
        elif c=='manual':
            user=core.input('Saved GitHub username: ').strip()
            if not user:return
        elif c=='active':user=None
        elif c and c.startswith('account:'):user=c[8:]
        else:return
        core.register(root,*ri,user)
    def hub(root):
        exists=(root/'.git').is_dir();ri=core.remote_info() if exists else None
        row=core.load().get(str(root),{}) if ri else {}
        core.print('Project:',root.name,'\nDestination:',ri[1] if ri else 'Local only','\nPinned account:',row.get('account','Not registered') if ri and row.get('remote')==ri[0] else 'Not registered')
        options=[('list','List saved GitHub identities'),('login','Add or renew an account (browser)'),('org','Organisation access / SSO guidance')]
        if ri:options[0:0]=[('choose','Choose account for this project'),('verify','Verify current account and repository')]
        else:options.insert(0,('connect','Connect or clone an existing repository'))
        while True:
            c=core.menu('Accounts & Organisations',options)
            if c=='list':
                if not ensure_gh(core):continue
                names=list_saved(core);core.print('Saved accounts: '+(', '.join(names) if names else 'No accounts discovered or account listing unavailable. Use Add or renew an account, or choose a known username.'))
            elif c=='login':login_now()
            elif c=='org':
                core.print('Use a personal or managed GitHub account with access to OWNER/REPO.\nIf SSO is required, visit https://github.com/orgs/ORGANISATION/sso (replace ORGANISATION), authorize GitHub CLI and verify again.\nAn account switch does not change the repository destination. New organisation repositories must be created on GitHub, then connected here.')
            elif c=='choose':
                try:select_account(root)
                except SystemExit as e:core.print(str(e))
            elif c=='verify':
                try:core.approved(root);core.print('Verified account, repository identity and write access. Branch rules may still block publication.')
                except SystemExit as e:core.print(str(e))
            elif c=='connect':core.connect(root,exists);return
            else:return
    def save_first(root,exists):
        if not exists:
            c=core.menu('Welcome — where should your work go?',[('publish','Publish a new GitHub repository'),('connect','Connect or clone an existing repository'),('local','Start a local repository — no login needed')],recommended='publish')
            if c=='publish':core.publish(root,False)
            elif c=='connect':core.connect(root,False)
            elif c=='local':core.init_local(root);core.print('Local repository created. Choose Save my work to create your first commit.')
            return
        if not core.remote_info():return original_save(root,exists)
        c=core.menu('Save my work',[('publish','Save and upload to GitHub'),('local','Save on this computer only')],recommended='publish')
        if c not in ('publish','local'):return
        core.stage_commit()
        if c=='publish':
            core.print('Local save complete. Checking GitHub before any upload; local commits remain if verification fails.')
            core.ensure_registered(root);core.push(root)
    def publish_named(root,exists):
        # Scope the input adapter to the verified personal-repository creation path.
        # The existing engine still validates the owner, reviews the destination,
        # checks for existing repositories, and requires independent push approval.
        prior=core.input
        def repository_input(prompt=''):
            match=re.fullmatch(r'New repository OWNER/NAME \[([A-Za-z0-9-]+)/([A-Za-z0-9_.-]+)\]: ',prompt)
            if match:
                owner,default=match.groups()
                core.print('Repository owner: '+owner+' (verified GitHub account).')
                while True:
                    name=prior('Repository name only ['+default+'] — owner: '+owner+': ').strip() or default
                    if name.casefold()=='cancel':core.stop('Repository creation cancelled. No repository created.')
                    if re.fullmatch(r'[A-Za-z0-9_.-]{1,100}',name) and name not in ('.','..') and not name.lower().endswith('.git'):
                        core.print('Destination: '+owner+'/'+name)
                        return owner+'/'+name
                    core.print('Enter only a repository name (letters, numbers, dots, hyphens, underscores). Do not enter the username or a slash. Try again, or cancel.')
            if prompt=='Enter PRIVATE or PUBLIC [PRIVATE]: ':
                choice=core.menu('Who can see your repository?',[('PRIVATE','Private — only authorised people'),('PUBLIC','Public — anyone can see the source')],recommended='PRIVATE')
                if choice not in ('PRIVATE','PUBLIC'):core.stop('Repository creation cancelled.')
                return choice
            return prior(prompt)
        core.input=repository_input
        try:return original_publish(root,exists)
        finally:core.input=prior
    def gh_path():
        gh=ensure_gh(core)
        if not gh:core.stop('GitHub CLI unavailable. Local work remains intact.')
        return gh
    core.publish=publish_named
    core.gh_path=gh_path
    core.run=run
    core.identity=identity
    core.ensure_registered=ensure_registered
    core.pick_account=choose_identity
    core.stage_commit=stage_with_identity
    core.login_action=login_now
    core.intent_save=save_first
    core.register_current=select_account
    # Existing action captures original function objects; replace these entries explicitly.
    from dataclasses import replace
    core.ACTIONS['register']=replace(core.ACTIONS['register'],handler=select_account)
    core.ACTIONS['login']=replace(core.ACTIONS['login'],handler=lambda r:login_now())
    core.ACTIONS['accounts-hub']=core.Action('accounts-hub','Fix','Accounts & Organisations','account accounts auth login switch organization organisation SSO permissions connection',hub,False)
    for term in re.findall(r'[a-z0-9]+','accounts-hub Accounts Organisations auth login switch organization SSO permissions connection'.lower()):core.INDEX[term].add('accounts-hub')
