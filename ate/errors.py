"""Typed errors raised by parsers.

M1 acceptance metric M1.i requires Tier-C edge case files to surface
specific error classes rather than crashes. Every parser must raise
one of these (or a subclass) for any failure case.
"""
from __future__ import annotations


class ATEParseError(Exception):
    """Base class for all parse-time errors."""


class UnsupportedFormatError(ATEParseError):
    """File format is not one of {pdf, docx, txt} or magic bytes mismatch."""


class CorruptDocumentError(ATEParseError):
    """File header recognized but contents are malformed."""


class PasswordProtectedError(ATEParseError):
    """File is encrypted and we cannot extract content."""


class EmptyDocumentError(ATEParseError):
    """File parses but contains no extractable text."""


class UnsupportedScannedPDFError(ATEParseError):
    """PDF has no text layer (scanned image-only). OCR is out of M1 scope."""


class EncodingError(ATEParseError):
    """Plain-text file uses an undecodable byte sequence."""
