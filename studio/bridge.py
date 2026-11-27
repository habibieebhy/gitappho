#!/usr/bin/env python3
"""Read-only snapshot and guarded v7 action handoff for GitAppho Studio."""
import json, os, sys, re, hashlib, contextlib, io
from pathlib import Path

def load_core(path):
    import importlib.util
    p=Path(path).resolve()
    spec=importlib.util.spec_from_file_location('gitappho_studio_core',p)
    mod=importlib.util.module_from_spec(spec); sys.modules[spec.name]=mod
    spec.loader.exec_module(mod)
    from accounts import install
    install(mod)
    return mod

def safe(s):
    # Prevent control characters in repository names or commit messages from becoming TUI commands.
    return ''.join(c if c.isprintable() else '?' for c in str(s))[:300]

def snapshot(core):
    result={'project':safe(Path.cwd().name),'branch':'—','connection':'Unknown','working':'Unknown','operation':[], 'history':[], 'actions':[], 'blocked':'','stash':0}
    os.environ['GIT_OPTIONAL_LOCKS']='0'
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            root,exists=core.boundary()
            if exists: core.config_guard()
            states=core.ongoing() if exists else []
            ri=core.remote_info() if exists else None
            result.update(project=safe(root.name),branch=safe(core.out('branch','--show-current') or '(detached)') if exists else 'New project',
                working=('Unfinished changes' if core.dirty() else 'Clean') if exists else 'Not initialised',
                connection=('Registered / not verified' if core.load().get(str(root),{}).get('remote')==ri[0] else 'Not registered') if ri else 'Local only',operation=states,
                stash=len(core.stash_entries()) if exists else 0)
            if exists and core.head():
                hist=core.git('--no-pager','log','--graph','--all','--no-color','--format=%h %s','-n','14',check=False)
                if hist.returncode==0: result['history']=[safe(x) for x in hist.stdout.splitlines()][:22]
            for a in core.ACTIONS.values():
                why=''
                if a.needs_repo and not exists: why='Requires a local repository'
                elif states and not a.during_operation: why='Resolve interrupted operation first'
                elif a.needs_remote and not ri: why='Requires a GitHub remote'
                elif a.key=='init' and exists: why='Already initialised'
                elif a.key=='conflict' and not states: why='No interrupted operation'
                elif a.key=='bisect' and states and 'BISECT_START' not in states: why='Finish other operation first'
                result['actions'].append({'key':a.key,'label':a.label,'group':a.group,'words':a.words,'blocked':why})
    except (SystemExit,OSError,ValueError,KeyError,TypeError,AttributeError):
        result['blocked']='Repository inspection blocked. Use classic mode for diagnostic details.'; result['actions']=[]
    return result

def main():
    if len(sys.argv)==3 and sys.argv[1]=='snapshot':
        print(json.dumps(snapshot(load_core(sys.argv[2])),ensure_ascii=True));return
    if len(sys.argv)==4 and sys.argv[1]=='workflow':
        from native_worker import run_workflow
        run_workflow(load_core(sys.argv[2]),sys.argv[2],sys.argv[3]);return
    raise SystemExit('Usage: bridge.py snapshot CORE | workflow CORE ACTION')
if __name__=='__main__':main()
