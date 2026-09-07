"""可复现的离线事实评估；使用可控Provider契约替身，不消耗模型额度。"""
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid5, NAMESPACE_URL
from application.fact_evaluation import evaluate_facts
from application.story_facts import source_digest
from service.value_objects.chapter_constraints import ChapterConstraintSet
from service.value_objects.story_fact import StoryEntity, StoryFactVersion, FactEvidence


def evaluation_snapshot(surname: str = '辛') -> ChapterConstraintSet:
    names = [('hall', 'place', surname + '家祖祠'), ('family', 'family', surname + '家'), ('other', 'family', '陆家'), ('hero', 'character', surname + '远')]
    entities = tuple(StoryEntity(id=uuid5(NAMESPACE_URL, key), entity_key=key, kind=kind, name=name) for key, kind, name in names)
    quote = surname + '家祖祠归' + surname + '家所有'
    source = quote + '。' + surname + '远姓' + surname + '。'
    evidence = FactEvidence(source_kind='human_confirmation', source_ref='synthetic-eval-v1', source_version=1, quote=quote, source_hash=source_digest(source))
    facts = (StoryFactVersion(id=uuid5(NAMESPACE_URL, 'hall-fact'), subject_id=entities[0].id, predicate='ancestral_hall_owner',
        object_entity_id=entities[1].id, evidence=evidence, version=1, created_at=datetime(2026, 9, 7, tzinfo=timezone.utc)),
        StoryFactVersion(id=uuid5(NAMESPACE_URL, 'surname-fact'), subject_id=entities[3].id, predicate='surname', value_text=surname,
        evidence=evidence.model_copy(update={'quote': surname + '远姓' + surname}), version=1, created_at=datetime(2026, 9, 7, tzinfo=timezone.utc)))
    return ChapterConstraintSet(tenant_id=UUID(int=1), novel_id=UUID(int=2), chapter_number=1, entities=entities, fact_heads=facts)


def evaluation_judge(mode: str, snapshot: ChapterConstraintSet) -> Any:
    if mode == 'none':
        return None
    async def generate(**kwargs: Any) -> dict[str, Any]:
        if mode == 'error':
            raise TimeoutError('synthetic provider timeout')
        if mode == 'malformed':
            return {'claims': 'invalid'}
        return {'coverage': 'partial' if mode == 'partial' else 'complete', 'unresolved': [], 'claims': [{
            'subject_id': str(snapshot.entities[0].id), 'predicate': 'ancestral_hall_owner',
            'object_entity_id': str(snapshot.entities[1].id), 'quote': snapshot.fact_heads[0].evidence.quote}]}
    return SimpleNamespace(structured_generate=generate)


async def run_evaluation(path: Path) -> dict[str, Any]:
    corpus = json.loads(path.read_text(encoding='utf-8'))
    results = []
    for case in corpus['cases']:
        snapshot = evaluation_snapshot()
        report = await evaluate_facts(snapshot, case['content'], 'body', evaluation_judge(case['judge'], snapshot))
        results.append({'id': case['id'], 'expected': case['expected'], 'observed': report.status, 'passed': report.status == case['expected']})
    return {'corpus_version': corpus['version'], 'cases': len(results), 'passed': sum(row['passed'] for row in results),
        'provider_calls': 0, 'provenance': corpus['provenance'], 'results': results}
