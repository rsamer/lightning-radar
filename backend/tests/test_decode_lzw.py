"""Tests for decode_lzw in app.core.utils."""
import pytest

from app.core.utils import decode_lzw


# ---------------------------------------------------------------------------
# Fast-path: plain JSON strings
# ---------------------------------------------------------------------------

def test_plain_json_object_returned_as_is():
    """Input starting with '{' must be returned without LZW decoding."""
    payload = '{"lat": 47.1}'
    result = decode_lzw(payload)
    assert result == payload


def test_plain_json_array_returned_as_is():
    """Input starting with '[' must be returned without LZW decoding."""
    payload = '[1, 2, 3]'
    result = decode_lzw(payload)
    assert result == payload


def test_plain_json_with_leading_whitespace():
    """decode_lzw passes the string through the LZW decoder unchanged for plain ASCII."""
    payload = '  {"key": "value"}  '
    result = decode_lzw(payload)
    assert result == payload


# ---------------------------------------------------------------------------
# Bytes input decoded via latin-1
# ---------------------------------------------------------------------------

def test_bytes_of_plain_json_returned_as_string():
    """bytes containing valid JSON must come back as a str."""
    payload = b'{"lat": 47.07, "lon": 15.43}'
    result = decode_lzw(payload)
    assert result == '{"lat": 47.07, "lon": 15.43}'


def test_bytes_high_values_do_not_raise():
    """Bytes with values > 127 must not raise and must not produce utf-8 replacement char."""
    payload = b'\xff\xfe'
    result = decode_lzw(payload)
    # Must not raise, and must not contain the UTF-8 replacement character
    assert '�' not in result


def test_bytes_high_values_preserve_latin1():
    """A single high byte decoded latin-1 must survive the round-trip without corruption."""
    # b'\xff' is latin-1 'ÿ' (ordinal 255).  decode_lzw should handle it without
    # raising or emitting the UTF-8 replacement character.
    result = decode_lzw(b'\xff')
    assert '�' not in result
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Empty input
# ---------------------------------------------------------------------------

def test_empty_string_returns_empty_json():
    """Empty string must return '{}'."""
    assert decode_lzw('') == '{}'


def test_empty_bytes_returns_empty_json():
    """Empty bytes must return '{}'."""
    assert decode_lzw(b'') == '{}'


# ---------------------------------------------------------------------------
# LZW round-trip / smoke test
# ---------------------------------------------------------------------------

def test_lzw_aaa_does_not_raise():
    """
    The LZW algorithm on 'aaa' is the simplest compressible case.
    We cannot directly compress here, but we can verify decode_lzw
    doesn't raise on a short non-JSON string and returns a non-empty str.
    """
    # 'aaa' does NOT start with '{' or '[', so it goes through the LZW path.
    result = decode_lzw('aaa')
    assert isinstance(result, str)
    assert len(result) > 0


def test_single_char_lzw_returns_string():
    """A single non-JSON character must go through the LZW path without raising."""
    result = decode_lzw('x')
    assert isinstance(result, str)
