import os
import re
import shutil
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from django.core.files import File
from django.db import transaction

from test_builder.models import OptionDraft, PDFImportJob, QuestionDraft, SectionDraft

try:
    import fitz
except ImportError:
    fitz = None

try:
    import boto3
except ImportError:
    boto3 = None

try:
    import pytesseract
except ImportError:
    pytesseract = None


QUESTION_START_RE = re.compile(r'^(?:q(?:uestion)?\s*)?(\d{1,3})\s*([\).:-])\s*(.+)?$', re.IGNORECASE)
OPTION_START_RE = re.compile(
    r'^(?:\(?([A-Ea-e1-5])\)|([A-Ea-e1-5])[\).:-])\s*(.+)?$'
)
INLINE_ANSWER_RE = re.compile(
    r'^(?:ans(?:wer)?|correct\s+answer)\s*[:\-]\s*([A-Ea-e1-5])\b',
    re.IGNORECASE,
)
ANSWER_HEADING_RE = re.compile(r'^(?:answer\s*key|answers?)\s*:?$', re.IGNORECASE)
ANSWER_PAIR_RE = re.compile(r'(\d{1,3})\s*[\).:-]?\s*([A-Ea-e1-5])\b')

IMPORT_CONFIDENCE_CUTOFF = float(os.getenv('PDF_IMPORT_CONFIDENCE_CUTOFF', '0.4'))


@dataclass
class ExtractedPage:
    page_number: int
    lines: list[str]
    image_path: str


@dataclass
class QuestionCandidate:
    number: int
    stem: str
    options: list[dict]
    correct_label: str | None
    source_pages: list[int]
    confidence: float


def _normalize_text(value):
    return re.sub(r'\s+', ' ', (value or '')).strip()


def _normalize_label(value):
    return (value or '').strip().upper()


def _stem_contains_option_markers(stem):
    markers = re.findall(r'(?:\([1-9A-Ea-e]\)|\b[A-Ea-e][\)\.])', stem or '')
    return len(markers) >= 2


def _is_noise_line(line):
    stripped = _normalize_text(line)
    if not stripped:
        return True
    if re.fullmatch(r'page\s*\d+|\d+', stripped, re.IGNORECASE):
        return True
    return False


def _merge_text(parts):
    return _normalize_text(' '.join(p for p in parts if p and p.strip()))


def _append_to_last(items, text):
    normalized = _normalize_text(text)
    if not normalized:
        return
    if items:
        items[-1] = _normalize_text(f"{items[-1]} {normalized}")
    else:
        items.append(normalized)


def _sequential_labels(labels):
    normalized = [_normalize_label(label) for label in labels if label]
    if len(normalized) < 2:
        return False
    if all(label.isdigit() for label in normalized):
        expected = [str(index) for index in range(1, len(normalized) + 1)]
        return normalized == expected
    letters = ['A', 'B', 'C', 'D', 'E']
    expected = letters[:len(normalized)]
    return normalized == expected


def _extract_answer_key(lines):
    answer_map = {}
    in_answer_zone = False

    for raw_line in lines:
        line = _normalize_text(raw_line)
        if not line:
            continue

        if ANSWER_HEADING_RE.match(line):
            in_answer_zone = True
            continue

        if in_answer_zone or len(ANSWER_PAIR_RE.findall(line)) >= 2:
            for question_number, label in ANSWER_PAIR_RE.findall(line):
                answer_map[int(question_number)] = _normalize_label(label)

    return answer_map


def _parse_candidates(pages):
    all_lines = [line for page in pages for line in page.lines]
    answer_key = _extract_answer_key(all_lines)
    candidates = []
    current = None
    current_page = None

    def finish_current():
        nonlocal current
        if not current:
            return

        stem = _merge_text(current['stem_parts'])
        options = []
        for option in current['options']:
            option_text = _merge_text(option['parts'])
            if option_text:
                options.append({'label': option['label'], 'text': option_text})

        correct_label = current.get('correct_label') or answer_key.get(current['number'])
        confidence = 0.0
        if stem:
            confidence += 0.25
        if 2 <= len(options) <= 5:
            confidence += 0.25
        if _sequential_labels([option['label'] for option in options]):
            confidence += 0.2
        if correct_label and any(_normalize_label(option['label']) == _normalize_label(correct_label) for option in options):
            confidence += 0.2
        if not _stem_contains_option_markers(stem):
            confidence += 0.1

        candidates.append(
            QuestionCandidate(
                number=current['number'],
                stem=stem,
                options=options,
                correct_label=_normalize_label(correct_label) if correct_label else None,
                source_pages=sorted(current['source_pages']),
                confidence=round(confidence, 2),
            )
        )
        current = None

    for page in pages:
        current_page = page.page_number
        for raw_line in page.lines:
            line = _normalize_text(raw_line)
            if _is_noise_line(line):
                continue
            if ANSWER_HEADING_RE.match(line):
                continue
            if len(ANSWER_PAIR_RE.findall(line)) >= 2:
                continue

            inline_answer = INLINE_ANSWER_RE.match(line)
            if inline_answer and current:
                current['correct_label'] = _normalize_label(inline_answer.group(1))
                continue

            question_match = QUESTION_START_RE.match(line)
            if question_match:
                number = int(question_match.group(1))
                delimiter = question_match.group(2)
                remainder = _normalize_text(question_match.group(3))

                if delimiter == ':' and remainder and len(remainder) <= 2:
                    continue

                finish_current()
                current = {
                    'number': number,
                    'stem_parts': [remainder] if remainder else [],
                    'options': [],
                    'correct_label': None,
                    'source_pages': {current_page},
                }
                continue

            option_match = OPTION_START_RE.match(line)
            if option_match and current:
                label = _normalize_label(option_match.group(1) or option_match.group(2))
                text = _normalize_text(option_match.group(3))
                current['options'].append({'label': label, 'parts': [text] if text else []})
                current['source_pages'].add(current_page)
                continue

            if not current:
                continue

            current['source_pages'].add(current_page)
            if current['options']:
                current['options'][-1]['parts'].append(line)
            else:
                current['stem_parts'].append(line)

    finish_current()
    return candidates


def _render_page_image(page, target_dir, page_number):
    image_path = Path(target_dir) / f'page-{page_number}.png'
    pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
    pixmap.save(image_path)
    return str(image_path)


def _extract_native_pages(pdf_path, persistent_dir):
    if fitz is None:
        raise RuntimeError('PyMuPDF is required for PDF import. Install the PyMuPDF package.')

    pages = []
    with fitz.open(pdf_path) as document:
        for index, page in enumerate(document, start=1):
            blocks = page.get_text('blocks', sort=True)
            lines = []
            for block in blocks:
                text = block[4] if len(block) > 4 else ''
                for block_line in text.splitlines():
                    normalized = _normalize_text(block_line)
                    if normalized:
                        lines.append(normalized)

            pages.append(
                ExtractedPage(
                    page_number=index,
                    lines=lines,
                    image_path=_render_page_image(page, persistent_dir, index),
                )
            )

    return pages


def _extract_with_textract(pages):
    if boto3 is None:
        return None

    region_name = os.getenv('AWS_REGION') or os.getenv('AWS_DEFAULT_REGION')
    if not region_name:
        return None

    try:
        client = boto3.client('textract', region_name=region_name)
    except Exception:
        return None

    extracted_pages = []
    try:
        for page in pages:
            with open(page.image_path, 'rb') as image_handle:
                response = client.detect_document_text(Document={'Bytes': image_handle.read()})
            lines = [
                _normalize_text(block.get('Text'))
                for block in response.get('Blocks', [])
                if block.get('BlockType') == 'LINE' and _normalize_text(block.get('Text'))
            ]
            extracted_pages.append(
                ExtractedPage(
                    page_number=page.page_number,
                    lines=lines,
                    image_path=page.image_path,
                )
            )
    except Exception:
        return None

    return extracted_pages


def _extract_with_tesseract(pages):
    if pytesseract is None:
        return None

    try:
        from PIL import Image
    except ImportError:
        return None

    extracted_pages = []
    try:
        for page in pages:
            image = Image.open(page.image_path)
            text = pytesseract.image_to_string(image, config='--psm 6')
            lines = [_normalize_text(line) for line in text.splitlines() if _normalize_text(line)]
            extracted_pages.append(
                ExtractedPage(
                    page_number=page.page_number,
                    lines=lines,
                    image_path=page.image_path,
                )
            )
    except Exception:
        return None

    return extracted_pages


def _select_best_extraction(pdf_path, persistent_dir):
    native_pages = _extract_native_pages(pdf_path, persistent_dir)
    native_candidates = _parse_candidates(native_pages)
    native_score = sum(1 for candidate in native_candidates if candidate.confidence >= IMPORT_CONFIDENCE_CUTOFF)
    native_text_size = sum(len(' '.join(page.lines)) for page in native_pages)
    preferred_provider = (os.getenv('PDF_IMPORT_PREFERRED_PROVIDER') or '').strip().lower()

    if native_score > 0:
        return native_pages, native_candidates, 'native-text'

    best_pages = native_pages
    best_candidates = native_candidates
    best_provider = 'native-text'
    best_score = native_score

    textract_pages = _extract_with_textract(native_pages)
    if textract_pages:
        textract_candidates = _parse_candidates(textract_pages)
        textract_score = sum(1 for candidate in textract_candidates if candidate.confidence >= IMPORT_CONFIDENCE_CUTOFF)
        if (
            textract_score > best_score
            or (textract_score == best_score and preferred_provider == 'aws-textract')
            or (best_score == 0 and len(textract_candidates) > len(best_candidates))
        ):
            best_pages = textract_pages
            best_candidates = textract_candidates
            best_provider = 'aws-textract'
            best_score = textract_score

    tesseract_pages = _extract_with_tesseract(native_pages)
    if tesseract_pages:
        tesseract_candidates = _parse_candidates(tesseract_pages)
        tesseract_score = sum(1 for candidate in tesseract_candidates if candidate.confidence >= IMPORT_CONFIDENCE_CUTOFF)
        if (
            tesseract_score > best_score
            or (tesseract_score == best_score and preferred_provider == 'tesseract')
            or (best_score == 0 and len(tesseract_candidates) > len(best_candidates))
        ):
            best_pages = tesseract_pages
            best_candidates = tesseract_candidates
            best_provider = 'tesseract'
            best_score = tesseract_score

    if best_provider == 'native-text' and native_text_size < 200:
        return native_pages, native_candidates, 'native-text'

    return best_pages, best_candidates, best_provider


def _pick_question_image(page_map, candidate, page_question_counts):
    if len(candidate.source_pages) != 1:
        return None

    page_number = candidate.source_pages[0]
    if page_question_counts.get(page_number) != 1:
        return None

    page = page_map.get(page_number)
    if not page:
        return None

    image_path = Path(page.image_path)
    if not image_path.exists():
        return None
    return image_path


@transaction.atomic
def import_pdf_into_section(section: SectionDraft, pdf_file, import_job: PDFImportJob | None = None) -> dict:
    if import_job:
        import_job.status = PDFImportJob.STATUS_RUNNING
        import_job.error_message = ''
        import_job.save(update_fields=['status', 'error_message', 'updated_at'])

    with tempfile.NamedTemporaryFile(prefix='exampattern-upload-', suffix='.pdf', delete=False) as temp_pdf:
        for chunk in pdf_file.chunks():
            temp_pdf.write(chunk)
        temp_pdf_path = Path(temp_pdf.name)

    persistent_dir = Path(tempfile.mkdtemp(prefix='exampattern-pdf-import-'))

    try:
        pages, candidates, provider_name = _select_best_extraction(temp_pdf_path, persistent_dir)
        page_map = {page.page_number: page for page in pages}
        page_question_counts = Counter(page for candidate in candidates for page in candidate.source_pages)

        base_order = section.questions.count()
        imported_count = 0
        skipped_count = 0
        skipped_reasons = Counter()
        auto_adjusted_count = 0

        for candidate in candidates:
            stem = _normalize_text(candidate.stem)
            options = candidate.options or []
            correct_label = _normalize_label(candidate.correct_label)

            if candidate.confidence < IMPORT_CONFIDENCE_CUTOFF:
                skipped_count += 1
                skipped_reasons['low confidence parse'] += 1
                continue

            if not stem:
                skipped_count += 1
                skipped_reasons['missing stem'] += 1
                continue

            if len(options) == 0:
                options = [{'label': 'A', 'text': 'Option A (auto-generated)'}]
                auto_adjusted_count += 1

            if _stem_contains_option_markers(stem):
                skipped_count += 1
                skipped_reasons['stem still contains option markers'] += 1
                continue

            normalized_options = []
            correct_matches = 0
            for option in options:
                option_text = _normalize_text(option.get('text'))
                option_label = _normalize_label(option.get('label'))
                if not option_text:
                    skipped_count += 1
                    skipped_reasons['empty option text'] += 1
                    normalized_options = []
                    break
                if len(option_text) > 500:
                    skipped_count += 1
                    skipped_reasons['option text exceeds draft limit'] += 1
                    normalized_options = []
                    break

                is_correct = option_label == correct_label
                if is_correct:
                    correct_matches += 1

                normalized_options.append({
                    'text': option_text,
                    'is_correct': is_correct,
                })

            if not normalized_options:
                normalized_options = [{'text': 'Option A (auto-generated)', 'is_correct': True}]
                auto_adjusted_count += 1

            if correct_matches != 1:
                for index, option in enumerate(normalized_options):
                    option['is_correct'] = index == 0
                auto_adjusted_count += 1

            question = QuestionDraft.objects.create(
                section=section,
                question_text=stem,
                order=base_order + imported_count + 1,
            )

            image_path = _pick_question_image(page_map, candidate, page_question_counts)
            if image_path:
                with image_path.open('rb') as image_handle:
                    question.question_image.save(image_path.name, File(image_handle), save=True)

            for option_index, option in enumerate(normalized_options, start=1):
                OptionDraft.objects.create(
                    question=question,
                    option_text=option['text'],
                    is_correct=option['is_correct'],
                    order=option_index,
                )

            imported_count += 1

        result = {
            'provider_name': provider_name,
            'imported_count': imported_count,
            'skipped_count': skipped_count,
            'auto_adjusted_count': auto_adjusted_count,
            'skip_summary': [f"{count} {reason}" for reason, count in sorted(skipped_reasons.items())],
        }

        if import_job:
            import_job.status = PDFImportJob.STATUS_COMPLETED
            import_job.provider_name = provider_name
            import_job.imported_count = imported_count
            import_job.skipped_count = skipped_count
            import_job.skip_summary = result['skip_summary']
            import_job.error_message = ''
            import_job.save(
                update_fields=[
                    'status',
                    'provider_name',
                    'imported_count',
                    'skipped_count',
                    'skip_summary',
                    'error_message',
                    'updated_at',
                ]
            )

        return result
    except Exception as exc:
        if import_job:
            import_job.status = PDFImportJob.STATUS_FAILED
            import_job.error_message = str(exc)
            import_job.save(update_fields=['status', 'error_message', 'updated_at'])
        raise
    finally:
        temp_pdf_path.unlink(missing_ok=True)
        shutil.rmtree(persistent_dir, ignore_errors=True)
