import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.core.engine import LunaEngine
from app.core.observer_layer import ObserverLayer
from app.core.vision_layer import VisionLayer
from app.models.nvidia_vision_model import NvidiaVisionModel


class VisionRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.model = Mock(spec=NvidiaVisionModel)
        self.model.supports_path.side_effect = lambda p: Path(p).suffix.lower() == '.png'
        self.model.is_available.return_value = True
        self.model.analyze_media.return_value = json.dumps({
            'detected_text': 'Build ready', 'detected_errors': [],
            'important_context': 'Terminal shows a successful build.',
        })
        self.layer = VisionLayer(self.model)

    def file(self, name, content=b'fixture'):
        p = self.root / name
        p.write_bytes(content)
        return str(p)

    def assert_failed(self, result):
        self.assertFalse(result['ok'])
        self.assertEqual(result['confidence'], 0.0)
        self.assertEqual(result['detected_text'], '')
        self.assertTrue(result['analysis_errors'])

    def test_missing_file_is_not_success(self):
        self.assert_failed(self.layer.analyze([str(self.root / 'missing.txt')]))

    def test_unsupported_pdf_is_not_success(self):
        self.assert_failed(self.layer.analyze([self.file('document.pdf')]))

    def test_directory_with_text_extension_is_not_document(self):
        p = self.root / 'folder.txt'
        p.mkdir()
        self.assert_failed(self.layer.analyze([str(p)]))

    def test_empty_document_is_not_success(self):
        self.assert_failed(self.layer.analyze([self.file('empty.txt', b'')]))

    def test_unreadable_document_is_not_success(self):
        p = self.file('denied.txt')
        with patch.object(Path, 'read_text', side_effect=PermissionError('denied')):
            self.assert_failed(self.layer.analyze([p]))

    def test_unconfigured_model_is_not_success(self):
        self.model.is_available.return_value = False
        self.assert_failed(self.layer.analyze([self.file('image.png')]))
        self.model.analyze_media.assert_not_called()

    def test_model_failure_is_not_recognized_text(self):
        self.model.analyze_media.side_effect = RuntimeError('upstream unavailable')
        result = self.layer.analyze([self.file('image.png')])
        self.assert_failed(result)
        self.assertEqual(result['raw_model_output'], '')
        self.assertEqual(result['detected_errors'], [])
        self.assertIn('upstream unavailable', self.layer.summarize(result))

    def test_empty_model_response_is_not_success(self):
        for output in ('', '{}', '{"confidence": 0.9}'):
            with self.subTest(output=output):
                self.model.analyze_media.return_value = output
                self.assert_failed(self.layer.analyze([self.file('image.png')]))

    def test_successful_image_analysis(self):
        result = self.layer.analyze([self.file('image.png')])
        self.assertTrue(result['ok'])
        self.assertEqual(result['detected_text'], 'Build ready')
        self.assertEqual(result['analysis_errors'], [])

    def test_visible_error_is_successful_observation(self):
        self.model.analyze_media.return_value = json.dumps({'detected_errors': ['TypeError: bad input']})
        result = self.layer.analyze([self.file('image.png')])
        self.assertTrue(result['ok'])
        self.assertEqual(result['detected_errors'], ['TypeError: bad input'])
        self.assertEqual(result['analysis_errors'], [])

    def test_document_error_is_successful_read(self):
        result = self.layer.analyze([self.file('build.log', b'TypeError: bad input')])
        self.assertTrue(result['ok'])
        self.assertIn('TypeError: bad input', result['detected_errors'])

    def test_partial_success_keeps_readable_content_and_reports_failure(self):
        self.model.analyze_media.side_effect = RuntimeError('offline')
        result = self.layer.analyze([self.file('notes.txt', b'Project requirements'), self.file('image.png')])
        self.assertTrue(result['ok'])
        self.assertIn('Project requirements', result['detected_text'])
        self.assertNotIn('offline', result['detected_text'])
        self.assertTrue(result['analysis_errors'])

    def test_czech_encodings_preserved_in_both_readers(self):
        text = 'P\u0159\u00edli\u0161 \u017elu\u0165ou\u010dk\u00fd k\u016f\u0148'
        for encoding in ('utf-8', 'utf-8-sig', 'cp1250'):
            with self.subTest(encoding=encoding):
                p = self.file('czech.txt', text.encode(encoding))
                self.assertIn(text, self.layer.analyze([p])['detected_text'])
                observed = ObserverLayer().read_log_file(p)['detected_text']
                self.assertEqual(observed, text)
                self.assertNotIn('\ufeff', observed)

    def test_no_inputs_remains_failure(self):
        self.assertFalse(self.layer.analyze([])['ok'])

    def test_engine_propagates_analysis_failure(self):
        engine = LunaEngine.__new__(LunaEngine)
        engine.vision_layer = self.layer
        result = engine.analyze_visual_media([str(self.root / 'missing.png')])
        self.assertFalse(result['ok'])
        self.assertIn('File not found', result['summary'])
        self.assertTrue(result['analysis']['analysis_errors'])

    def test_attachment_context_preserves_czech_document(self):
        engine = LunaEngine.__new__(LunaEngine)
        engine.vision_layer = self.layer
        text = '\u010cesk\u00fd dokument'
        result = engine.read_attachment_context([self.file('document.txt', text.encode('cp1250'))])
        self.assertIn(text, result)
        self.assertIn('"ok": true', result)


if __name__ == '__main__':
    unittest.main()
