"""Regression coverage for the September repository and PyPI audit."""
import json
from html.parser import HTMLParser
from unittest.mock import patch

import pytest
from trikedb import TrikeDB, OntologyError


def test_core_roundtrip_and_join(tmp_path):
    p = tmp_path / 'core.yaml'
    db = TrikeDB(p, ontology=['P', 'Q'])
    with db.batch():
        db.add('日本語', 'P', 'b', note='source')
        db.add('b', 'Q', 'c')
        db.set_node('b', type='table', pii=True)
    db = TrikeDB(p)
    assert db.query(['?a P ?b', '?b Q ?c']) == [{'a': '日本語', 'b': 'b', 'c': 'c'}]
    assert db.sparql('ASK {t:b t:pii true}')
    assert db.sparql('SELECT ?a WHERE {?a t:P/t:Q t:c}') == [{'a': '日本語'}]
    assert db.remove(s='b', p='Q') == 1
    assert len(TrikeDB(p)) == 1


@pytest.mark.parametrize('query', [
    'PREFIX ex: <urn:trikedb:> INSERT DATA {ex:a ex:P ex:b}',
    '# an update\nINSERT DATA {t:a t:P t:b}',
])
def test_sparql_update_accepts_prefixes_and_comments(query):
    db = TrikeDB()
    assert db.sparql(query) == 1


@pytest.mark.parametrize('value', ['"hello"', '42', '"bonjour"@fr'])
def test_update_preserves_rdf_literal(value, tmp_path):
    p = tmp_path / 'literal.yaml'
    db = TrikeDB(p)
    db.update(f'INSERT DATA {{t:a t:P {value}}}')
    assert TrikeDB(p).sparql(f'ASK {{t:a t:P {value}}}') is True


def test_sparql_reads_node_properties_on_update():
    db = TrikeDB()
    db.set_node('a', pii=True)
    db.update('INSERT {?s t:P t:restricted} WHERE {?s t:pii true}')
    assert ('a', 'P', 'restricted') in db


def test_reload_replaces_ontology(tmp_path):
    p = tmp_path / 'ontology.yaml'
    db = TrikeDB(p, ontology={'OLD': 'old'})
    db.save()
    p.write_text('ontology: {predicates: {NEW: new}}\ntriples: []\n')
    db.reload()
    assert db.ontology == {'NEW': 'new'}


def test_returned_triple_is_a_detached_snapshot():
    db = TrikeDB()
    t = db.add('a', 'P', 'b', score=1)
    assert db.sparql('ASK {?st t:score 1}')
    t.attrs['score'] = 2
    assert not db.sparql('ASK {?st t:score 2}')
    assert next(db.triples()).attrs['score'] == 1
    db.add('a', 'P', 'b', score=2)
    assert db.sparql('ASK {?st t:score 2}')


def test_jsonld_matches_rdf_projection():
    from rdflib import Graph
    from rdflib.compare import isomorphic
    db = TrikeDB()
    db.add('a', 'P', 'b', prov='source')
    db.set_node('a', type='table')
    projected = Graph().parse(data=json.dumps(db.to_jsonld()), format='json-ld')
    assert isomorphic(projected, db.to_rdflib())


@pytest.mark.parametrize('attrs', [{'label': 'edge title'}, {'key': 'external-id'}])
def test_networkx_accepts_freeform_attributes(attrs):
    db = TrikeDB()
    db.add('a', 'P', 'b', **attrs)
    assert db.to_networkx().number_of_edges() == 1


def test_export_does_not_inject_script():
    class Scripts(HTMLParser):
        def __init__(self):
            super().__init__()
            self.inside = False
            self.scripts = []
        def handle_starttag(self, tag, attrs):
            self.inside = tag == 'script'
        def handle_endtag(self, tag):
            if tag == 'script':
                self.inside = False
        def handle_data(self, data):
            if self.inside:
                self.scripts.append(data)
    db = TrikeDB()
    db.set_node('doc', description='</script><script>window.REVIEW_INJECTED=1</script>')
    parser = Scripts()
    parser.feed(db.to_html())
    assert 'window.REVIEW_INJECTED=1' not in parser.scripts


def test_successful_save_does_not_adopt_other_writers_version():
    # Deterministically schedule a competing commit between PUT and HEAD.
    # Mock only storage, retaining the real save/reload/mutation logic.
    import trikedb.persistence as core
    from trikedb.storage import ConcurrentWriteError
    state = {'doc': 'triples: []', 'version': 0, 'inject': True}
    def write(path, text, expect, connection=None):
        if expect != state['version']:
            raise ConcurrentWriteError('stale')
        state['doc'], state['version'] = text, state['version'] + 1
        committed = state['version']
        if state['inject']:
            import yaml
            doc = yaml.safe_load(text)
            doc['triples'].append({'s': 'other-writer', 'p': 'P', 'o': 'b'})
            state['doc'] = yaml.safe_dump(doc)
            state['version'] += 1
            state['inject'] = False
        return committed
    with patch.object(core, '_exists', return_value=True), \
         patch.object(core, '_version_of', side_effect=lambda *a: state['version']), \
         patch.object(core, '_read_text', side_effect=lambda *a, **k: state['doc']), \
         patch.object(core, '_write_text', side_effect=write):
        db = TrikeDB('s3://review/graph.yaml')
        db.add('a', 'P', 'b')
        try:
            db.add('c', 'P', 'd')
        except ConcurrentWriteError:
            pass
        assert 'other-writer' in state['doc']


def test_rest_and_mcp_share_graph(tmp_path):
    from starlette.testclient import TestClient
    from trikedb.serve import build_app
    p = tmp_path / 'served.yaml'
    TrikeDB(p).add('initial', 'P', 'b')
    with TestClient(build_app(p, public_url='http://testserver', stateless=True)) as c:
        result = c.post('/mcp', headers={'Accept': 'application/json, text/event-stream'},
                        json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                              'params': {'name': 'add_triple', 'arguments':
                                         {'s': 'mcp-write', 'p': 'P', 'o': 'b'}}})
        assert result.status_code == 200 and 'mcp-write' in result.text
        assert ('mcp-write', 'P', 'b') in TrikeDB(p)
        visible = c.post('/sparql', json={'query': 'ASK {t:mcp-write t:P t:b}'}).json()
        c.post('/sparql', json={'query': 'INSERT DATA {t:rest-write t:P t:b}'})
        assert visible == {'ask': True}, {'rest_read': visible, 'disk_after_rest': list(TrikeDB(p))}
        assert ('mcp-write', 'P', 'b') in TrikeDB(p)


def test_local_save_failure_preserves_previous_file(tmp_path):
    from pathlib import Path
    p = tmp_path / 'durable.yaml'
    db = TrikeDB(p)
    db.add('saved', 'P', 'b')
    original = p.read_text()
    from trikedb import storage
    with patch.object(storage.os, 'replace', side_effect=OSError('interrupted replacement')):
        with pytest.raises(OSError):
            db.add('next', 'P', 'b')

    assert p.read_text() == original


def test_reserved_statement_node_does_not_collide():
    db = TrikeDB()
    db.add('a', 'P', 'b', source='x')
    db.add('stmt0', 'P', 'c')
    assert db.sparql('ASK {t:stmt0 a rdf:Statement}') is False


def test_failed_batch_does_not_leak_on_next_write(tmp_path):
    p = tmp_path / 'batch.yaml'
    db = TrikeDB(p)
    db.add('initial', 'P', 'b')
    with pytest.raises(ValueError):
        with db.batch():
            db.add('failed-operation', 'P', 'b')
            raise ValueError('abort')
    db.add('unrelated', 'P', 'b')
    assert ('failed-operation', 'P', 'b') not in TrikeDB(p)


@pytest.mark.parametrize('engine', ['oxigraph', 'rdflib'])
def test_rdf_terms_with_same_lexical_value_and_empty_literal(tmp_path, engine):
    from rdflib.compare import isomorphic
    p = tmp_path / 'terms.yaml'
    db = TrikeDB(p, sparql_engine=engine)
    db.update('INSERT DATA {t:a t:P t:hello, "hello", "hello"@en, "", "42"^^<http://www.w3.org/2001/XMLSchema#integer> . _:x t:P t:a}')
    reread = TrikeDB(p, sparql_engine=engine)
    assert len(reread) == 6
    assert reread.sparql('ASK {t:a t:P t:hello, "hello", "hello"@en, "", 42 . ?x t:P t:a FILTER(isBlank(?x))}')
    assert isomorphic(db.to_rdflib(), reread.to_rdflib())
    assert reread.to_networkx().number_of_edges() == 6


def test_rdf_explicit_iri_object_with_spaces():
    db = TrikeDB()
    db.add('a', 'P', 'New York', rdf_terms={'o': {'kind': 'iri'}})
    assert db.sparql('ASK {t:a t:P <urn:trikedb:New%20York>}')


def test_ontology_cannot_be_bypassed_by_rdf_predicate_override():
    db = TrikeDB(ontology=['P'])
    with pytest.raises(OntologyError):
        db.add('a', 'P', 'b', rdf_terms={'p': {'kind': 'iri', 'value': 'urn:trikedb:OTHER'}})
    assert not len(db)


@pytest.mark.parametrize('query', [
    'INSERT DATA {GRAPH t:g {t:a t:P t:b}}',
    'LOAD <https://example.invalid/data>',
    'CLEAR ALL',
    'WITH t:g INSERT {t:a t:P t:b} WHERE {}',
    'INSERT {t:a t:P t:b} USING t:g WHERE {}',
    'DELETE WHERE {?s t:pii ?o}',
])
def test_unsupported_updates_fail_before_persistence(query, tmp_path):
    db = TrikeDB(tmp_path / 'unsupported.yaml')
    db.set_node('a', pii=True)
    original = db.path.read_text()
    with pytest.raises(ValueError):
        db.update(query)
    assert db.path.read_text() == original


def test_batch_restores_after_commit_failure_and_nested_failure(tmp_path):
    db = TrikeDB(tmp_path / 'batch.yaml')
    db.add('a', 'P', 'b')
    with pytest.raises(OSError):
        with patch('trikedb.storage.os.replace', side_effect=OSError('fail')):
            with db.batch():
                db.add('failed', 'P', 'b')
    assert len(db) == 1
    with db.batch():
        db.add('outer', 'P', 'b')
        with pytest.raises(ValueError):
            with db.batch():
                db.set_node('a', type='lost')
                raise ValueError('rollback inner')
        db.add('outer2', 'P', 'b')
    assert len(TrikeDB(db.path)) == 3
    assert db.node('a') == {}


def test_local_save_preserves_symlink_and_permissions(tmp_path):
    target = tmp_path / 'target.yaml'
    TrikeDB(target).add('a', 'P', 'b')
    target.chmod(0o640)
    link = tmp_path / 'link.yaml'
    link.symlink_to(target)
    TrikeDB(link).add('c', 'P', 'd')
    assert link.is_symlink()
    assert target.stat().st_mode & 0o777 == 0o640
    assert len(TrikeDB(target)) == 2


def test_inference_apply_preserves_literal_type(tmp_path):
    db = TrikeDB(tmp_path / 'inferred.yaml')
    db.declare('P', 'subproperty_of:Q')
    db.update('INSERT DATA {t:a t:P "bonjour"@fr}')
    db.infer(apply=True)
    assert TrikeDB(db.path).sparql('ASK {t:a t:Q "bonjour"@fr}')


def test_f1_is_bounded_for_many_matches_in_one_prediction():
    from benchmarks.webqsp_bench import f1
    assert f1('Alice Bob', ['Alice', 'Bob']) == 1
    assert 0 <= f1('Alice\nAlice\nwrong', ['Alice', 'Bob']) <= 1


def test_cli_edge_boolean_attributes_roundtrip(tmp_path):
    import subprocess
    import sys
    path = tmp_path / 'cli.yaml'
    subprocess.run([sys.executable, '-m', 'trikedb.cli', 'add', str(path),
                    'a', 'P', 'b', '-a', 'deprecated=false', '-a', 'verified=true'],
                   check=True, capture_output=True, text=True)
    attrs = next(TrikeDB(path).triples()).attrs
    assert attrs['deprecated'] is False
    assert attrs['verified'] is True
