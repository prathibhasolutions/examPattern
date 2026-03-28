"""
copy_import.py — Copy questions/sections from existing tests into a draft.

Supports two source types:
  - "draft"     : SectionDraft → QuestionDraft / OptionDraft  (draft tests)
  - "published" : Section (testseries)  → Question / Option   (live tests)

All copies are deep clones; editing a copy never affects the original.
Images are referenced (same file path), not physically duplicated.
"""

from django.db import transaction

from test_builder.models import QuestionDraft, OptionDraft, SectionDraft
from testseries.models import Test, Section
from questions.models import Question


# ── Source listing ────────────────────────────────────────────────────

def list_source_tests():
    """
    Return a serialisable list of all tests that can be used as copy sources.
    Each entry has: id, name, source_type, series_name, sections[].
    """
    results = []

    # 1. Published tests (live Test objects) — include even inactive ones
    for test in (
        Test.objects
        .select_related('series')
        .prefetch_related('sections')
        .order_by('series__name', 'name')
    ):
        sections = [
            {
                'id': sec.id,
                'name': sec.name,
                'question_count': sec.questions.filter(is_active=True).count(),
                'source_type': 'published',
            }
            for sec in test.sections.filter(is_active=True).order_by('order')
        ]
        if sections:
            results.append({
                'id': test.id,
                'name': test.name,
                'source_type': 'published',
                'series_name': test.series.name,
                'is_active': test.is_active,
                'sections': sections,
            })

    # 2. Draft tests (TestDraft objects) — include all drafts visible on the system
    from test_builder.models import TestDraft
    for draft in (
        TestDraft.objects
        .select_related('series')
        .prefetch_related('sections__questions')
        .order_by('series__name', 'name')
    ):
        sections = [
            {
                'id': sec.id,
                'name': sec.name,
                'question_count': sec.questions.count(),
                'source_type': 'draft',
            }
            for sec in draft.sections.order_by('order')
            if sec.questions.exists()
        ]
        if sections:
            results.append({
                'id': draft.id,
                'name': draft.name,
                'source_type': 'draft',
                'series_name': draft.series.name,
                'is_published': draft.is_published,
                'sections': sections,
            })

    return results


def list_questions_in_source_section(source_type: str, section_id: int):
    """
    Return a serialisable list of questions in one source section, for preview.
    """
    questions = []

    if source_type == 'published':
        section = Section.objects.filter(id=section_id, is_active=True).first()
        if not section:
            return []
        for q in section.questions.filter(is_active=True).order_by('id'):
            questions.append({
                'id': q.id,
                'order': q.pk,   # use pk as stable identifier
                'question_text': q.text,
                'image_url': q.image.url if q.image else None,
                'options': [
                    {
                        'text': opt.text,
                        'is_correct': opt.is_correct,
                    }
                    for opt in q.options.order_by('order')
                ],
            })

    elif source_type == 'draft':
        section = SectionDraft.objects.filter(id=section_id).first()
        if not section:
            return []
        for q in section.questions.order_by('order'):
            questions.append({
                'id': q.id,
                'order': q.order,
                'question_text': q.question_text,
                'image_url': q.question_image.url if q.question_image else None,
                'options': [
                    {
                        'text': opt.option_text,
                        'is_correct': opt.is_correct,
                    }
                    for opt in q.options.order_by('order')
                ],
            })

    return questions


# ── Actual copy ───────────────────────────────────────────────────────

@transaction.atomic
def copy_questions_into_section(
    target_section: SectionDraft,
    source_type: str,
    source_section_id: int,
    question_ids: list,          # empty list → copy all questions in the section
) -> dict:
    """
    Deep-clone the selected questions (+ their options) from a source section
    into `target_section`.

    Returns {'copied': int, 'skipped': int, 'errors': [str]}
    """
    copied = 0
    skipped = 0
    errors = []

    start_order = target_section.questions.count() + 1

    if source_type == 'published':
        source_section = Section.objects.filter(id=source_section_id, is_active=True).first()
        if not source_section:
            return {'copied': 0, 'skipped': 0, 'errors': ['Source section not found.']}

        qs = source_section.questions.filter(is_active=True).order_by('id')
        if question_ids:
            qs = qs.filter(id__in=question_ids)

        for q in qs:
            options = list(q.options.order_by('order'))
            # Basic integrity check: must have at least 2 options and 1 correct
            if len(options) < 2 or not any(o.is_correct for o in options):
                skipped += 1
                continue

            new_q = QuestionDraft.objects.create(
                section=target_section,
                question_text=q.text,
                question_image=q.image,          # same file reference
                solution_text=q.explanation,
                solution_image=q.solution_image,
                order=start_order,
            )
            start_order += 1

            for opt in options:
                OptionDraft.objects.create(
                    question=new_q,
                    option_text=opt.text,
                    option_image=opt.image,      # same file reference
                    is_correct=opt.is_correct,
                    order=opt.order,
                )
            copied += 1

    elif source_type == 'draft':
        source_section = SectionDraft.objects.filter(id=source_section_id).first()
        if not source_section:
            return {'copied': 0, 'skipped': 0, 'errors': ['Source section not found.']}

        qs = source_section.questions.order_by('order')
        if question_ids:
            qs = qs.filter(id__in=question_ids)

        for q in qs:
            options = list(q.options.order_by('order'))
            if len(options) < 2 or not any(o.is_correct for o in options):
                skipped += 1
                continue

            new_q = QuestionDraft.objects.create(
                section=target_section,
                question_text=q.question_text,
                question_image=q.question_image,
                solution_text=q.solution_text,
                solution_image=q.solution_image,
                order=start_order,
            )
            start_order += 1

            for opt in options:
                OptionDraft.objects.create(
                    question=new_q,
                    option_text=opt.option_text,
                    option_image=opt.option_image,
                    is_correct=opt.is_correct,
                    order=opt.order,
                )
            copied += 1

    else:
        return {'copied': 0, 'skipped': 0, 'errors': [f'Unknown source_type: {source_type}']}

    return {'copied': copied, 'skipped': skipped, 'errors': errors}
