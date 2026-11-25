"""Versioned, bounded Python research notebooks, using QuantLab's isolated runner."""
from contextlib import closing
from hashlib import sha256
import json
import math
import uuid

from . import user_scripts as library

MAX_CELLS = 30
MAX_CODE = 20000
MAX_DOCUMENT = 512000
MAX_REVISIONS = 500
MAX_RUNS = 300
MAX_TEXT = 12000


def validate_document(title, cells, snapshot=None):
    if not isinstance(title,str) or not 1 <= len(title.strip()) <= 100:
        raise ValueError("Enter a notebook title")
    if not isinstance(cells,list) or not 1 <= len(cells) <= MAX_CELLS:
        raise ValueError("A notebook requires 1-30 cells")
    clean=[]
    for c in cells:
        if not isinstance(c,dict) or c.get("kind") not in ("markdown","code") or not isinstance(c.get("source"),str):
            raise ValueError("Each cell needs a kind and source text")
        if len(c["source"]) > MAX_CODE:
            raise ValueError("Cell exceeds 20,000 characters")
        if c["kind"]=="code":
            try:
                compile(c["source"],"<notebook cell>","exec")
            except SyntaxError as exc:
                raise ValueError(f"Cell {len(clean)+1}, line {exc.lineno}: {exc.msg}") from exc
        clean.append({"kind":c["kind"],"source":c["source"]})
    if sum(len(c["source"]) for c in clean)>MAX_CODE:
        raise ValueError("Notebook text and code together exceed 20,000 characters")
    data=json.loads(library.snapshot_json(snapshot)) if snapshot is not None else None
    doc={"title":title.strip(),"cells":clean,"snapshot":data}
    raw=json.dumps(doc,ensure_ascii=False,allow_nan=False)
    if len(raw.encode())>MAX_DOCUMENT:
        raise ValueError("Notebook and copied input exceed 512 KB; select a smaller dataset")
    return doc,raw


def list_notebooks():
    with closing(library._connect()) as db:
        return [dict(r) for r in db.execute("SELECT * FROM research_notebooks ORDER BY updated_utc DESC")]


def read_notebook(ident,revision=None):
    if not isinstance(ident,str) or not library.ID.fullmatch(ident):
        raise ValueError("Invalid notebook ID")
    with closing(library._connect()) as db:
        head=db.execute("SELECT revision FROM research_notebooks WHERE id=?",(ident,)).fetchone()
        if head is None:
            raise ValueError("Notebook not found")
        revision=head["revision"] if revision is None else revision
        row=db.execute("SELECT * FROM notebook_revisions WHERE notebook_id=? AND revision=?",(ident,revision)).fetchone()
        if row is None:
            raise ValueError("Notebook revision not found")
        return {**json.loads(row["payload"]),"id":ident,"revision":revision,
                "source_sha256":row["source_sha256"],
                "revisions":[dict(r) for r in db.execute("SELECT revision,created_utc FROM notebook_revisions WHERE notebook_id=? ORDER BY revision DESC",(ident,))],
                "runs":[dict(r) for r in db.execute("SELECT id,revision,created_utc FROM notebook_runs WHERE notebook_id=? ORDER BY created_utc DESC",(ident,))]}


def save_notebook(*,title,cells,snapshot=None,notebook_id=None,expected_revision=None):
    doc,raw=validate_document(title,cells,snapshot)
    now=library._now()
    with closing(library._connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT count(*) FROM notebook_revisions").fetchone()[0]>=MAX_REVISIONS:
            raise ValueError("Notebook revision library is full; export notebooks")
        if notebook_id is None:
            if expected_revision is not None:
                raise ValueError("Unexpected revision for a new notebook")
            notebook_id=uuid.uuid4().hex
            revision=1
            db.execute("INSERT INTO research_notebooks VALUES(?,?,?,?)",(notebook_id,doc["title"],revision,now))
        else:
            if not library.ID.fullmatch(notebook_id):
                raise ValueError("Invalid notebook ID")
            head=db.execute("SELECT revision FROM research_notebooks WHERE id=?",(notebook_id,)).fetchone()
            if head is None or head["revision"]!=expected_revision:
                raise ValueError("Notebook changed elsewhere; reopen or Save as new")
            revision=head["revision"]+1
            db.execute("UPDATE research_notebooks SET title=?,revision=?,updated_utc=? WHERE id=?",(doc["title"],revision,now,notebook_id))
        db.execute("INSERT INTO notebook_revisions VALUES(?,?,?,?,?)",(notebook_id,revision,raw,sha256(raw.encode()).hexdigest(),now))
    return read_notebook(notebook_id,revision)


RUNNER=r'''
import ast,contextlib,json,os
class Text:
    def __init__(self): self.text=""
    def write(self,s):
        self.text+=(str(s)[:max(0,12000-len(self.text))])
        return len(s)
    def flush(self): pass
with open("/work/notebook.json",encoding="utf-8") as f:
    request=json.load(f)
env={"__name__":"__quantlab_notebook__","data":request["snapshot"]}
outputs=[]
for i,cell in enumerate(request["cells"]):
    if cell["kind"]!="code": continue
    buf=Text()
    charts=[]
    def display(value): print(repr(value))
    def show_chart(title,x_label,y_label,x,traces):
        if len(charts)>=2: raise ValueError("At most two charts per cell")
        charts.append({"title":title,"x_label":x_label,"y_label":y_label,"x":list(x),"traces":traces})
    env.update(display=display,show_chart=show_chart)
    error=None
    try:
        with contextlib.redirect_stdout(buf),contextlib.redirect_stderr(buf):
            tree=ast.parse(cell["source"],filename="cell-"+str(i+1),mode="exec")
            if tree.body and isinstance(tree.body[-1],ast.Expr):
                last=tree.body.pop().value
                exec(compile(tree,"cell-"+str(i+1),"exec"),env)
                value=eval(compile(ast.Expression(last),"cell-"+str(i+1),"eval"),env)
                if value is not None: display(value)
            else:
                exec(compile(tree,"cell-"+str(i+1),"exec"),env)
    except BaseException as exc:
        error=type(exc).__name__+": "+str(exc)[:300]
    outputs.append({"index":i,"text":buf.text,"charts":charts,"error":error})
    if error is not None: break
with open("/work/result.json","w",encoding="utf-8") as f:
    json.dump({"outputs":outputs},f,ensure_ascii=False,allow_nan=False)
'''


def validate_results(result,cells):
    outputs=result.get("outputs") if isinstance(result,dict) else None
    indices=[i for i,c in enumerate(cells) if c["kind"]=="code"]
    if not isinstance(outputs,list) or len(outputs)>len(indices):
        raise ValueError("Invalid notebook output")
    clean=[]
    for i,r in enumerate(outputs):
        if not isinstance(r,dict) or r.get("index")!=indices[i] or not isinstance(r.get("text"),str):
            raise ValueError("Notebook cell result does not match execution order")
        err=r.get("error")
        if err is not None and not isinstance(err,str):
            raise ValueError("Invalid notebook error")
        charts=r.get("charts",[])
        if not isinstance(charts,list) or len(charts)>2:
            raise ValueError("Invalid notebook charts")
        plots=[]
        for chart in charts:
            if not isinstance(chart,dict):
                raise ValueError("Invalid notebook chart")
            x=chart.get("x")
            if not isinstance(x,list) or not 1<=len(x)<=library.MAX_ROWS or any(
                not ((type(v) is str and len(v)<=160) or (type(v) in (int,float) and abs(v)<=1e100 and math.isfinite(v))) for v in x):
                raise ValueError("Chart requires finite or text X coordinates")
            plot=library.validate_output(chart,len(x))
            plot.update(kind="line2d",x=x)
            plots.append(plot)
        clean.append({"index":r["index"],"text":r["text"][:MAX_TEXT],"charts":plots,"error":err[:400] if err else None})
        if err and i!=len(outputs)-1:
            raise ValueError("Unexpected output after failed cell")
    if len(clean)!=len(indices) and (not clean or not clean[-1]["error"]):
        raise ValueError("Incomplete notebook results")
    return clean


def run_notebook(*,notebook_id,revision,through=None,profile="stdlib",progress=None):
    doc=read_notebook(notebook_id,revision)
    if through is not None and not 0<=through<len(doc["cells"]):
        raise ValueError("Choose a valid cell")
    cells=doc["cells"] if through is None else doc["cells"][:through+1]
    if not any(c["kind"]=="code" for c in cells):
        raise ValueError("No Python cells selected")
    payload=json.dumps({"cells":cells,"snapshot":doc["snapshot"]},ensure_ascii=False,allow_nan=False).encode()
    result=library.isolated_json(RUNNER,{"notebook.json":payload},profile,progress)
    outputs=validate_results(result,cells)
    ident=uuid.uuid4().hex
    output={"id":ident,"notebook_id":notebook_id,"revision":revision,"source_sha256":doc["source_sha256"],
            "input_sha256":sha256(payload).hexdigest(),"profile":profile,"created_utc":library._now(),
            "outputs":outputs,"complete":not any(r["error"] for r in outputs)}
    raw=json.dumps(output,ensure_ascii=False,allow_nan=False)
    if len(raw.encode())>2_000_000:
        raise ValueError("Notebook output exceeds 2 MB")
    with closing(library._connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT count(*) FROM notebook_runs").fetchone()[0]>=MAX_RUNS:
            raise ValueError("Notebook run library is full; export existing results")
        db.execute("INSERT INTO notebook_runs VALUES(?,?,?,?,?)",(ident,notebook_id,revision,output["created_utc"],raw))
    return output


def read_run(notebook_id,run_id):
    if not library.ID.fullmatch(notebook_id) or not library.ID.fullmatch(run_id):
        raise ValueError("Invalid notebook or run ID")
    with closing(library._connect()) as db:
        row=db.execute("SELECT payload FROM notebook_runs WHERE notebook_id=? AND id=?",(notebook_id,run_id)).fetchone()
        if row is None: raise ValueError("Notebook run not found")
        return json.loads(row["payload"])
