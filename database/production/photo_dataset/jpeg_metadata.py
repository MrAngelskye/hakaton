"""Remove optional JPEG metadata losslessly; never decode/re-encode pixels.

APP0/JFIF, APP2/ICC and APP14/Adobe are preserved byte for byte. APP1
(EXIF/XMP), APP13 (Photoshop/IPTC), and COM are removed. Author/license
information remains in manifest.json and ATTRIBUTIONS.md.
"""
import hashlib
from dataclasses import dataclass

REMOVABLE_MARKERS = frozenset({0xE1, 0xED, 0xFE})
PROTECTED_MARKERS = frozenset({0xE0, 0xE2, 0xEE})


@dataclass(frozen=True)
class Segment:
    marker: int
    start: int
    end: int


def jpeg_segments(blob):
    """Parse markers including scans; reject trailers and malformed boundaries."""
    if not blob.startswith(b'\xff\xd8'):
        raise ValueError('Not a JPEG SOI stream')
    result = [Segment(0xD8, 0, 2)]
    position = 2
    while position < len(blob):
        start = position
        if blob[position] != 0xFF:
            raise ValueError('Invalid JPEG marker boundary')
        while position < len(blob) and blob[position] == 0xFF:
            position += 1
        if position >= len(blob):
            raise ValueError('Truncated JPEG marker')
        marker = blob[position]
        position += 1
        if marker == 0xD9:
            result.append(Segment(marker, start, position))
            if position != len(blob):
                raise ValueError('Unexpected bytes after JPEG EOI')
            return result
        if marker in {0x00, 0xD8} or 0xD0 <= marker <= 0xD7:
            raise ValueError('Unexpected standalone JPEG marker')
        if marker == 0x01:
            result.append(Segment(marker, start, position))
            continue
        if position + 2 > len(blob):
            raise ValueError('Truncated JPEG segment length')
        length = int.from_bytes(blob[position:position + 2], 'big')
        if length < 2 or position + length > len(blob):
            raise ValueError('Invalid JPEG segment length')
        position += length
        if marker == 0xDA:
            # SOS header plus entropy bytes; FF00 is stuffed data and restart
            # markers remain part of the scan. Other markers end the scan.
            while True:
                boundary = blob.find(b'\xff', position)
                if boundary < 0:
                    raise ValueError('Missing JPEG EOI')
                following = boundary + 1
                while following < len(blob) and blob[following] == 0xFF:
                    following += 1
                if following >= len(blob):
                    raise ValueError('Truncated JPEG entropy stream')
                code = blob[following]
                if code == 0x00 or 0xD0 <= code <= 0xD7:
                    position = following + 1
                    continue
                position = boundary
                break
        result.append(Segment(marker, start, position))
    raise ValueError('Missing JPEG EOI')


def marker_name(marker):
    return 'COM' if marker == 0xFE else 'APP' + str(marker - 0xE0)


def optional_metadata(blob):
    return [
        {'segment': marker_name(segment.marker), 'bytes': segment.end - segment.start}
        for segment in jpeg_segments(blob) if segment.marker in REMOVABLE_MARKERS
    ]


def jpeg_scan_sha256(blob):
    digest = hashlib.sha256()
    for segment in jpeg_segments(blob):
        if segment.marker == 0xDA:
            digest.update(blob[segment.start:segment.end])
    return digest.hexdigest()


def protected_segments_sha256(blob):
    digest = hashlib.sha256()
    for segment in jpeg_segments(blob):
        if segment.marker in PROTECTED_MARKERS:
            digest.update(blob[segment.start:segment.end])
    return digest.hexdigest()


def strip_optional_metadata(blob):
    """Return sanitized JPEG bytes without modifying compressed image data."""
    segments = jpeg_segments(blob)
    cleaned = b''.join(
        blob[segment.start:segment.end]
        for segment in segments if segment.marker not in REMOVABLE_MARKERS
    )
    if jpeg_scan_sha256(blob) != jpeg_scan_sha256(cleaned):
        raise ValueError('Compressed JPEG scan changed unexpectedly')
    if protected_segments_sha256(blob) != protected_segments_sha256(cleaned):
        raise ValueError('Color-management/JFIF segments changed unexpectedly')
    return cleaned
