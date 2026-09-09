"""Regression tests for benchmark validity; no network or model calls."""
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from trikedb import TrikeDB

BENCH = Path(__file__).resolve().parents[1] / 'benchmarks'
sys.path.insert(0, str(BENCH))
import webqsp_bench as wq
import memory_bench as mb
import retrieval_bench as rb
import agent_bench as ab
from run_manifest import check_resume


def test_invalid_denominators():
    for recs in ([], [{'id':'x'}, {'id':'x'}], [{'id':'foreign'}]):
        with pytest.raises(ValueError):
            wq.validate_records(recs, {'x':[]})
    with pytest.raises(ValueError):
        wq.validate_records([{'id':'x','model':'a'}, {'id':'y','model':'b'}], {'x':[], 'y':[]})
    with pytest.raises(ValueError):
        wq._wilson(0, 0)


def test_no_partial_answer_paths_or_zero_budget():
    db=TrikeDB(autosave=False)
    db.add('start', 'p', 'middle'); db.add('middle', 'p', 'answer')
    assert rb._dedupe(db.triples(), 0)==[]
    assert mb.curate(db, 'q', ['start'], ['answer'], 1)==[]
    assert len(mb.curate(db, 'q', ['start'], ['answer'], 2))==2


def test_resume_fingerprint(tmp_path):
    source=tmp_path/'eval.json'; source.write_text('[]')
    out=tmp_path/'answers.jsonl'
    check_resume(out, {'model':'a'}, [source]);out.write_text('{"id":"x"}\n')
    check_resume(out, {'model':'a'}, [source])
    with pytest.raises(ValueError):check_resume(out, {'model':'b'}, [source])
    source.write_text('[1]')
    with pytest.raises(ValueError):check_resume(out, {'model':'a'}, [source])


def test_claude_json_object_and_array(monkeypatch,tmp_path):
    result={'type':'result','result':'answer','usage':{'input_tokens':5,'cache_read_input_tokens':10}}
    for payload in (result,[result]):
        monkeypatch.setattr(ab.subprocess,'run',lambda *a,**k:SimpleNamespace(stdout=json.dumps(payload),stderr='',returncode=0))
        record=ab._ask(tmp_path,'q','model','none')
        assert record['answer']=='answer' and record['total_input_tokens']==15


def test_codex_does_not_add_reasoning_subset(monkeypatch,tmp_path):
    events=[{'type':'turn.completed','usage':{'input_tokens':100,'output_tokens':30,'reasoning_output_tokens':20}}, {'type':'item.completed','item':{'type':'agent_message','text':'answer'}}]
    monkeypatch.setattr(ab.subprocess,'run',lambda *a,**k:SimpleNamespace(stdout='\n'.join(map(json.dumps,events)),stderr='',returncode=0))
    assert ab._ask_codex(tmp_path,'q','model','none')['output_tokens']==30


def test_workspace_does_not_delete_existing_files(tmp_path):
    existing=tmp_path/'none';existing.mkdir();(existing/'keep').write_text('keep')
    with pytest.raises(FileExistsError):ab._workspace(tmp_path,'none',tmp_path)
    assert (existing/'keep').read_text()=='keep'


def test_backend_cleanup_is_scoped_on_failure(monkeypatch,tmp_path):
    import backend_bench as bb
    from trikedb import storage_sql
    calls=[]
    class Fake:
        def __init__(self,*a,**k):pass
        def __len__(self):return 1
        def save(self,target=None):
            if str(target).startswith('snowflake://'):
                raise RuntimeError('write failed')
        def sparql(self,*a):return []
        def add(self,*a):pass
    monkeypatch.setattr(bb,'TABLE','TEST.PUBLIC.BENCH')
    monkeypatch.setattr(bb,'SIZES',[3])
    monkeypatch.setattr(bb,'build',lambda n:Fake())
    monkeypatch.setattr(bb,'TrikeDB',Fake)
    monkeypatch.setattr(storage_sql,'open_url',lambda url:SimpleNamespace(_run=lambda sql,params,**k:calls.append((sql,params))))
    with pytest.raises(RuntimeError,match='write failed'):bb._measure(tmp_path)
    assert len(calls)==1
    sql,params=calls[0]
    assert 'WHERE name = %s' in sql and 'LIKE' not in sql
    assert params[0].startswith('bench/') and params[0].endswith('/g3')
