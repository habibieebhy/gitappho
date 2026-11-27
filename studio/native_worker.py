"""Studio interaction adapter. No Git mutations are implemented here."""
import ast, contextlib, inspect, io, json, os, re, sys, threading, uuid
from pathlib import Path

# Only static menu strings from the pinned engine become interactive options.
def legacy_menus(path):
    result={}
    for fn in ast.parse(Path(path).read_text()).body:
        if not isinstance(fn,ast.FunctionDef): continue
        for node in ast.walk(fn):
            if not isinstance(node,ast.Call) or not isinstance(node.func,ast.Name) or node.func.id!='print': continue
            for arg in node.args:
                if not isinstance(arg,ast.Constant) or not isinstance(arg.value,str): continue
                options=[]
                for line in arg.value.splitlines():
                    m=re.fullmatch(r'(\d+)\s+(.+)',line.strip())
                    if m: options.append({'value':m[1],'label':m[2]})
                if len(options)>1 and any(x['value']=='0' for x in options):
                    if fn.name in result: raise RuntimeError('Ambiguous static menu: '+fn.name)
                    result[fn.name]=options
    return result

def visible(s):
    return ''.join(c if c=='\n' or c.isprintable() else '    ' if c=='\t' else f'\\x{ord(c):02x}' for c in str(s))

class Protocol:
    def __init__(self):
        self.reply=os.fdopen(os.dup(0),'r',encoding='utf-8')
        self.wire=os.fdopen(os.dup(1),'w',encoding='utf-8',buffering=1)
        self.lock=threading.Lock(); self.size=0; self.overflow=False; self.sequence=0
        self.marker='GITAPPHO-BARRIER-'+uuid.uuid4().hex
        self.drained=threading.Event()
        # Git, gh, hooks and other child processes never inherit the protocol stream.
        with open(os.devnull,'rb') as null: os.dup2(null.fileno(),0)
        read,write=os.pipe(); os.dup2(write,1);os.dup2(write,2);os.close(write)
        self.reader=os.fdopen(read,'rb')
        self.thread=threading.Thread(target=self.drain,daemon=True);self.thread.start()
    def send(self,event):
        with self.lock:
            self.wire.write(json.dumps(event,ensure_ascii=True)+'\n');self.wire.flush()
    def output(self,s):
        s=visible(s)
        # Split long output into bounded protocol messages, never silently drop review content.
        with self.lock:
            if self.overflow: return
            if self.size+len(s)>2_000_000:
                self.overflow=True
                self.wire.write(json.dumps({'kind':'output','text':'\nOutput limit reached. Further approvals blocked; inspect in IDE.\n'})+'\n');self.wire.flush();return
            self.size+=len(s)
            for i in range(0,len(s),4000):
                self.wire.write(json.dumps({'kind':'output','text':s[i:i+4000]},ensure_ascii=True)+'\n')
            self.wire.flush()
    def drain(self):
        import codecs
        decode=codecs.getincrementaldecoder('utf-8')('backslashreplace')
        while True:
            line=self.reader.readline(4096)
            if not line:break
            if line.rstrip(b'\r\n')==self.marker.encode(): self.drained.set();continue
            self.output(decode.decode(line))
    def flush(self):
        sys.stdout.flush();sys.stderr.flush();self.drained.clear()
        os.write(1,('\n'+self.marker+'\n').encode())
        if not self.drained.wait(5): raise EOFError('Output stream could not be verified')
    def ask(self,kind,title,options=None,default=0):
        self.flush()
        if self.overflow: raise EOFError('Review output exceeded limit')
        self.sequence+=1; seq=self.sequence
        self.send({'kind':'prompt','id':seq,'mode':kind,'text':visible(title),'options':options or [],'default':default})
        line=self.reply.readline(65537)
        if not line or len(line)>65536:raise EOFError('Studio input closed')
        obj=json.loads(line)
        if obj.get('id')!=seq or obj.get('cancel'):raise EOFError('Action cancelled')
        value=obj.get('value')
        if not isinstance(value,str) or len(value)>8192 or '\n' in value or '\r' in value or '\0' in value:raise EOFError('Invalid Studio response')
        if options is not None and value not in {o['value'] for o in options}:raise EOFError('Unknown selection')
        return value

def attach(core,protocol,path):
    menus=legacy_menus(path)
    original_confirm=core.confirm; original_header=core.session_header
    def output(*args,sep=' ',end='\n',file=None,flush=False):
        if file not in (None,sys.stdout,sys.stderr): return print(*args,sep=sep,end=end,file=file,flush=flush)
        protocol.output(sep.join(map(str,args))+end)
    def input_prompt(prompt=''):
        caller=sys._getframe(1).f_code.co_name
        if prompt.strip()=='Choose:' and caller in menus:
            return protocol.ask('choice',caller.replace('_',' ').capitalize(),menus[caller])
        if re.search(r'\[y/N\]',prompt,re.I):
            return protocol.ask('choice',prompt,[{'value':'n','label':'No / back'},{'value':'y','label':'Yes'}])
        return protocol.ask('text',prompt)
    def menu(title,choices,*,recommended=None):
        # The Go dashboard owns top-level navigation. A single action per worker;
        # existing persistent_session still owns locks, guards, journal and verification.
        if title=='What do you want to do?':return None
        options=[{'value':str(k),'label':visible(label)+('  [recommended]' if k==recommended else '')} for k,label in choices]
        options.append({'value':'','label':'Back / cancel'})
        val=protocol.ask('choice',title,options, next((i for i,(k,_) in enumerate(choices) if k==recommended),0))
        return val or None
    def confirm(word,message):
        # Retain the engine's confirmation validation; only replace its input transport.
        def approval(_=''):
            return protocol.ask('confirm',message,[{'value':'CANCEL','label':'Cancel / keep current state'},{'value':word,'label':'Approve — '+word}])
        prior=core.input;core.input=approval
        try: return original_confirm(word,message)
        finally:core.input=prior
    def header(*args):
        prior=core.print;core.print=lambda *a,**k:None
        try:return original_header(*args)
        finally:core.print=prior
    core.print=output;core.input=input_prompt;core.menu=menu;core.confirm=confirm;core.session_header=header

def run_workflow(core,path,key):
    p=Protocol()
    try:
        if key not in core.ACTIONS:raise SystemExit('Unknown action')
        attach(core,p,path)
        root,exists=core.boundary()
        if exists:core.config_guard()
        core.persistent_session(root,key)
    except (SystemExit,KeyboardInterrupt,EOFError,OSError,ValueError,KeyError,TypeError,AttributeError) as e:
        p.output('\nAction stopped: '+str(e)+'\nInspect actual state before retrying.\n')
    finally:
        try:p.flush()
        except (EOFError,OSError,KeyboardInterrupt):pass
        p.send({'kind':'done','text':'Action ended. Review results and actual repository state before repeating.'})
