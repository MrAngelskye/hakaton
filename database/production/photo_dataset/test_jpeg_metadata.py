"""Meaningful lossless-metadata checks using in-memory JPEG fixtures only."""
import io
import unittest
from PIL import Image
from jpeg_metadata import jpeg_segments, jpeg_scan_sha256, optional_metadata, protected_segments_sha256, strip_optional_metadata


def fixture(progressive=False):
    stream = io.BytesIO()
    Image.new('RGB', (8, 8), (25, 80, 120)).save(stream, format='JPEG', progressive=progressive)
    return stream.getvalue()


def segment(marker, payload):
    return bytes([0xFF, marker]) + (len(payload) + 2).to_bytes(2, 'big') + payload


class LosslessMetadataTest(unittest.TestCase):
    def test_removes_optional_segments_and_preserves_pixels(self):
        original = fixture()
        extra = segment(0xE1, b'Exif\x00\x00test') + segment(0xED, b'Photoshop 3.0\x00test') + segment(0xFE, b'test comment')
        decorated = original[:2] + extra + original[2:]
        cleaned = strip_optional_metadata(decorated)
        self.assertEqual(cleaned, original)
        self.assertEqual(optional_metadata(cleaned), [])
        self.assertEqual(jpeg_scan_sha256(decorated), jpeg_scan_sha256(cleaned))

    def test_preserves_color_segments_and_progressive_scans(self):
        original = fixture(progressive=True)
        preserved = segment(0xE2, b'ICC_PROFILE\x00test') + segment(0xEE, b'Adobe\x00test')
        decorated = original[:2] + preserved + segment(0xE1, b'Exif\x00\x00test') + original[2:]
        cleaned = strip_optional_metadata(decorated)
        self.assertEqual(cleaned, original[:2] + preserved + original[2:])
        self.assertGreater(sum(s.marker == 0xDA for s in jpeg_segments(cleaned)), 1)
        self.assertEqual(protected_segments_sha256(decorated), protected_segments_sha256(cleaned))

    def test_rejects_truncated_or_trailing_data(self):
        original = fixture()
        for broken in (b'not a jpeg', original[:-2], original + b'private trailer'):
            with self.assertRaises(ValueError):
                strip_optional_metadata(broken)


if __name__ == '__main__':
    unittest.main()
