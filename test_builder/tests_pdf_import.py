from django.test import SimpleTestCase
from unittest.mock import patch

from test_builder.services.pdf_import import (
    ExtractedPage,
    QuestionCandidate,
    _auto_latex_text,
    _parse_candidates,
    _select_best_image_extraction,
    _select_best_extraction,
)


class PDFImportParserTests(SimpleTestCase):
    def test_auto_latex_converts_common_math_patterns(self):
        text = 'Find x^2 if H2SO4 has 2 atoms and sqrt(16) = 4 and a ≤ b.'
        converted = _auto_latex_text(text)

        self.assertIn('$x^{2}$', converted)
        self.assertIn('$H_{2}SO_{4}$', converted)
        self.assertIn('$\\sqrt{16}$', converted)
        self.assertIn('$\\le$', converted)

    def test_auto_latex_keeps_existing_latex_unchanged(self):
        text = 'Already formatted $x^2 + y^2$ relation'
        converted = _auto_latex_text(text)

        self.assertEqual(converted, text)

    def test_parses_mcqs_and_answer_key(self):
        pages = [
            ExtractedPage(
                page_number=1,
                image_path='page-1.png',
                lines=[
                    '1. What is 2 + 2?',
                    'A. 3',
                    'B. 4',
                    'C. 5',
                    '2. Capital of France?',
                    'A. Berlin',
                    'B. Madrid',
                    'C. Paris',
                    'Answer Key',
                    '1 B 2 C',
                ],
            )
        ]

        candidates = _parse_candidates(pages)

        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[0].correct_label, 'B')
        self.assertEqual(candidates[1].correct_label, 'C')
        self.assertEqual(candidates[0].options[1]['text'], '4')
        self.assertGreaterEqual(candidates[0].confidence, 0.7)

    def test_parses_inline_answer_lines(self):
        pages = [
            ExtractedPage(
                page_number=1,
                image_path='page-1.png',
                lines=[
                    'Q1) The largest planet is',
                    'A) Earth',
                    'B) Jupiter',
                    'C) Mars',
                    'Answer: B',
                ],
            )
        ]

        candidates = _parse_candidates(pages)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].correct_label, 'B')
        self.assertEqual(candidates[0].options[1]['text'], 'Jupiter')

    @patch('test_builder.services.pdf_import._extract_with_tesseract')
    @patch('test_builder.services.pdf_import._extract_with_textract')
    @patch('test_builder.services.pdf_import._parse_candidates')
    @patch('test_builder.services.pdf_import._extract_native_pages')
    def test_select_best_extraction_uses_ocr_when_native_has_no_confident_candidates(
        self,
        mock_native_pages,
        mock_parse_candidates,
        mock_textract,
        mock_tesseract,
    ):
        native_pages = [ExtractedPage(page_number=1, lines=['random text'], image_path='p1.png')]
        textract_pages = [ExtractedPage(page_number=1, lines=['1. Test', 'A. a', 'B. b', 'Answer: B'], image_path='p1.png')]
        native_candidates = [
            QuestionCandidate(
                number=1,
                stem='noise',
                options=[],
                correct_label=None,
                source_pages=[1],
                confidence=0.2,
            )
        ]
        textract_candidates = [
            QuestionCandidate(
                number=1,
                stem='Test',
                options=[{'label': 'A', 'text': 'a'}, {'label': 'B', 'text': 'b'}],
                correct_label='B',
                source_pages=[1],
                confidence=0.8,
            )
        ]

        mock_native_pages.return_value = native_pages
        mock_textract.return_value = textract_pages
        mock_tesseract.return_value = None
        mock_parse_candidates.side_effect = [native_candidates, textract_candidates]

        pages, candidates, provider = _select_best_extraction('dummy.pdf', 'dummy-dir')

        self.assertEqual(provider, 'aws-textract')
        self.assertEqual(pages, textract_pages)
        self.assertEqual(candidates, textract_candidates)

    @patch('test_builder.services.pdf_import._extract_with_tesseract')
    @patch('test_builder.services.pdf_import._extract_with_textract')
    @patch('test_builder.services.pdf_import._parse_candidates')
    def test_select_best_image_extraction_prefers_higher_confidence_provider(
        self,
        mock_parse_candidates,
        mock_textract,
        mock_tesseract,
    ):
        native_pages = [ExtractedPage(page_number=1, lines=[], image_path='img1.png')]
        textract_pages = [ExtractedPage(page_number=1, lines=['1. Test', 'A. a', 'B. b', 'Answer: B'], image_path='img1.png')]
        tesseract_pages = [ExtractedPage(page_number=1, lines=['1. Test', 'A. a', 'B. b', 'Answer: B'], image_path='img1.png')]
        textract_candidates = [
            QuestionCandidate(
                number=1,
                stem='Test',
                options=[{'label': 'A', 'text': 'a'}, {'label': 'B', 'text': 'b'}],
                correct_label='B',
                source_pages=[1],
                confidence=0.5,
            )
        ]
        tesseract_candidates = [
            QuestionCandidate(
                number=1,
                stem='Test',
                options=[{'label': 'A', 'text': 'a'}, {'label': 'B', 'text': 'b'}],
                correct_label='B',
                source_pages=[1],
                confidence=0.8,
            )
        ]

        mock_textract.return_value = textract_pages
        mock_tesseract.return_value = tesseract_pages
        mock_parse_candidates.side_effect = [textract_candidates, tesseract_candidates]

        pages, candidates, provider = _select_best_image_extraction(native_pages)

        self.assertEqual(provider, 'tesseract')
        self.assertEqual(pages, tesseract_pages)
        self.assertEqual(candidates, tesseract_candidates)

    @patch('test_builder.services.pdf_import._extract_with_tesseract')
    @patch('test_builder.services.pdf_import._extract_with_textract')
    def test_select_best_image_extraction_raises_when_no_provider_available(
        self,
        mock_textract,
        mock_tesseract,
    ):
        native_pages = [ExtractedPage(page_number=1, lines=[], image_path='img1.png')]
        mock_textract.return_value = None
        mock_tesseract.return_value = None

        with self.assertRaises(RuntimeError):
            _select_best_image_extraction(native_pages)