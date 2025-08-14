#!/usr/bin/env python3

"""
Regex pattern parser with support for complex patterns.
"""

from typing import List, Optional, Set, Tuple, Union

from tools.logger import get_logger

from .segment import (
    CharClassSegment,
    FixedSegment,
    GroupSegment,
    OptionalSegment,
    Segment,
)
from .types import IRegexParser

logger = get_logger("refine")


class RegexParser(IRegexParser):
    """Parse regex patterns into segment sequences."""

    def __init__(self, max_quantifier_length: int = 150):
        self.max_quantifier_length = max_quantifier_length

    def parse(self, pattern: str) -> List[Segment]:
        """Parse regex pattern into segments."""
        if not pattern:
            return []

        pos, length = 0, len(pattern)
        segments = list()

        try:
            while pos < length:
                segment, pos = self._parse_next(pattern, pos, length)
                if segment:
                    segment.position = len(segments)
                    segments.append(segment)
                else:
                    break

            self._calculate_prefix_lengths(segments)
            return segments

        except Exception as e:
            logger.warning(f"Failed to parse pattern '{pattern}': {e}")
            return []

    def _parse_next(self, pattern: str, pos: int, length: int) -> Tuple[Optional[Segment], int]:
        """Parse next segment from current position."""
        if pos >= length:
            return None, pos

        char = pattern[pos]

        if char == "(":
            return self._parse_group(pattern, pos, length)
        elif char == "[":
            return self._parse_charclass(pattern, pos, length)
        elif char in r".*+?{}^$|\\":
            return self._parse_special(pattern, pos, length)
        else:
            return self._parse_fixed(pattern, pos, length)

    def _parse_group(self, pattern: str, pos: int, length: int) -> Tuple[Optional[Segment], int]:
        """Parse group patterns (...) or (?:...) or (?-i) etc."""
        start_pos = pos
        pos += 1  # Skip '('

        if pos >= length:
            return None, pos

        # Check for special group prefixes like ?:, ?-i, etc.
        non_capturing = False
        original_prefix = ""

        if pos < length and pattern[pos] == "?":
            # Parse special group syntax
            prefix_start = pos
            pos += 1  # Skip '?'

            if pos < length:
                if pattern[pos] == ":":
                    # Non-capturing group (?:...)
                    non_capturing = True
                    original_prefix = "?:"
                    pos += 1
                elif pos + 1 < length and pattern[pos] == "-" and pattern[pos + 1] == "i":
                    # Case sensitive flag (?-i)
                    original_prefix = "?-i"
                    pos += 2
                    non_capturing = True
                else:
                    # Other special syntax - preserve as-is
                    while pos < length and pattern[pos] not in "):":
                        pos += 1
                    original_prefix = pattern[prefix_start:pos]
                    if pos < length and pattern[pos] == ":":
                        pos += 1
                        non_capturing = True

        # Find matching closing parenthesis
        paren_count = 1
        group_start = pos

        while pos < length and paren_count > 0:
            if pattern[pos] == "(":
                paren_count += 1
            elif pattern[pos] == ")":
                paren_count -= 1
            pos += 1

        if paren_count > 0:
            logger.warning("Unmatched parentheses in pattern")
            return None, pos

        # Parse group content - preserve original for complex structures
        group_pattern = pattern[group_start : pos - 1]

        # For choice patterns like (sid01|api03), treat as single fixed content
        if "|" in group_pattern and not any(char in group_pattern for char in "[]{}*+?()"):
            # This is a simple choice pattern, create a single fixed segment
            choice_segment = FixedSegment()
            choice_segment.position = 0
            choice_segment.content = group_pattern
            group_content = [choice_segment]
        else:
            # Parse normally for other patterns - use same config
            sub_parser = RegexParser(self.max_quantifier_length)
            group_content = sub_parser.parse(group_pattern)

        # Check for quantifier
        quantifier, pos = self._parse_quantifier(pattern, pos, length)

        if quantifier == "?":
            segment = OptionalSegment()
            segment.position = start_pos
            segment.content = group_content
            return segment, pos
        else:
            segment = GroupSegment()
            segment.position = start_pos
            segment.content = group_content
            segment.capturing = not non_capturing
            # Store original prefix to preserve special flags
            if original_prefix:
                segment.original_prefix = original_prefix
            # Store quantifier to preserve group repetition like {3}
            if quantifier:
                segment.quantifier = quantifier
            return segment, pos

    def _parse_charclass(self, pattern: str, pos: int, length: int) -> Tuple[Optional[CharClassSegment], int]:
        """Parse character class [...]"""
        start_pos = pos
        pos += 1  # Skip '['

        if pos >= length:
            return None, pos

        # Find closing bracket
        class_content = ""
        while pos < length and pattern[pos] != "]":
            class_content += pattern[pos]
            pos += 1

        if pos >= length:
            logger.warning("Unclosed character class")
            return None, pos

        pos += 1  # Skip ']'

        # Parse character set
        charset = self._parse_charset(class_content)
        if not charset:
            return None, pos

        # Parse quantifier
        quantifier, pos = self._parse_quantifier(pattern, pos, length)
        min_len, max_len = self._quantifier_to_range(quantifier)

        # Detect case sensitivity from pattern
        case_sensitive = self._detect_case_sensitivity(pattern)

        segment = CharClassSegment()
        segment.position = start_pos
        segment.charset = charset
        segment.min_length = min_len
        segment.max_length = max_len
        segment.original_quantifier = quantifier
        segment.original_charset_str = f"[{class_content}]"  # Store original with escapes
        segment.case_sensitive = case_sensitive
        return segment, pos

    def _parse_charset(self, content: str) -> Set[str]:
        """Parse character class content into character set."""
        chars = set()
        i = 0
        length = len(content)

        while i < length:
            if i + 2 < length and content[i + 1] == "-":
                # Handle ranges like a-z, A-Z, 0-9
                start = content[i]
                end = content[i + 2]

                # Handle escaped characters
                if start == "\\" and i + 1 < length:
                    start = self._unescape_char(content[i + 1])
                    i += 1
                if end == "\\" and i + 3 < length:
                    end = self._unescape_char(content[i + 3])
                    i += 1

                # Add range characters
                try:
                    for c in range(ord(start), ord(end) + 1):
                        chars.add(chr(c))
                except ValueError:
                    logger.warning(f"Invalid character range: {start}-{end}")

                i += 3
            elif content[i] == "\\" and i + 1 < length:
                # Handle escaped characters
                escaped = self._unescape_char(content[i + 1])
                if escaped == "d":
                    chars.update("0123456789")
                elif escaped == "w":
                    chars.update("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")
                elif escaped == "s":
                    chars.update(" \t\n\r\f\v")
                else:
                    chars.add(escaped)
                i += 2
            else:
                # Regular character
                chars.add(content[i])
                i += 1

        return chars

    def _unescape_char(self, char: str) -> str:
        """Unescape special characters."""
        escape_map = {"n": "\n", "t": "\t", "r": "\r", "f": "\f", "v": "\v", "\\": "\\", "-": "-", "]": "]", "[": "["}
        return escape_map.get(char, char)

    def _parse_quantifier(self, pattern: str, pos: int, length: int) -> Tuple[str, int]:
        """Parse quantifier {n,m}, +, *, ?"""
        if pos >= length:
            return "", pos

        char = pattern[pos]

        if char == "{":
            start = pos
            while pos < length and pattern[pos] != "}":
                pos += 1
            if pos < length:
                pos += 1  # Skip '}'
                return pattern[start:pos], pos
        elif char in "+*?":
            pos += 1
            return char, pos

        return "", pos

    def _quantifier_to_range(self, quantifier: str) -> Tuple[int, Union[int, float]]:
        """Convert quantifier to length range."""
        if not quantifier:
            return (1, 1)
        elif quantifier == "+":
            return (1, self.max_quantifier_length)
        elif quantifier == "*":
            return (0, self.max_quantifier_length)
        elif quantifier == "?":
            return (0, 1)
        elif quantifier.startswith("{") and quantifier.endswith("}"):
            content = quantifier[1:-1]
            try:
                if "," in content:
                    parts = content.split(",")
                    min_val = int(parts[0]) if parts[0] else 0
                    max_val = int(parts[1]) if parts[1] else float("inf")
                    return (min_val, max_val)
                else:
                    val = int(content)
                    return (val, val)
            except ValueError:
                logger.warning(f"Invalid quantifier: {quantifier}")
                return (1, 1)
        else:
            return (1, 1)

    def _parse_special(self, pattern: str, pos: int, length: int) -> Tuple[Optional[Segment], int]:
        """Parse special characters and escape sequences preserving original format."""
        char = pattern[pos]

        if char == "\\" and pos + 1 < length:
            next_char = pattern[pos + 1]

            # Handle \w and \d as character classes
            if next_char == "w":
                pos += 2
                # Parse quantifier
                quantifier, pos = self._parse_quantifier(pattern, pos, length)
                min_len, max_len = self._quantifier_to_range(quantifier)

                # Create character class for \w
                segment = CharClassSegment()
                segment.position = pos - 2
                segment.charset = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")
                segment.min_length = min_len
                segment.max_length = max_len
                segment.original_quantifier = quantifier
                segment.original_charset_str = "[a-zA-Z0-9_]"
                segment.case_sensitive = self._detect_case_sensitivity(pattern)
                return segment, pos

            elif next_char == "d":
                pos += 2
                # Parse quantifier
                quantifier, pos = self._parse_quantifier(pattern, pos, length)
                min_len, max_len = self._quantifier_to_range(quantifier)

                # Create character class for \d
                segment = CharClassSegment()
                segment.position = pos - 2
                segment.charset = set("0123456789")
                segment.min_length = min_len
                segment.max_length = max_len
                segment.original_quantifier = quantifier
                segment.original_charset_str = "[0-9]"
                segment.case_sensitive = self._detect_case_sensitivity(pattern)
                return segment, pos
            else:
                # Handle other escape sequences - preserve original escape
                original_escape = pattern[pos : pos + 2]
                pos += 2
                segment = FixedSegment()
                segment.position = pos - 2
                segment.content = original_escape  # Preserve original escape like \/
                return segment, pos
        else:
            # Handle other special characters as fixed content
            pos += 1
            segment = FixedSegment()
            segment.position = pos - 1
            segment.content = char
            return segment, pos

    def _parse_fixed(self, pattern: str, pos: int, length: int) -> Tuple[FixedSegment, int]:
        """Parse fixed string segment preserving escape sequences."""
        start_pos = pos
        content = ""

        while pos < length and pattern[pos] not in r"()[].*+?{}^$|\\":
            content += pattern[pos]
            pos += 1

        segment = FixedSegment()
        segment.position = start_pos
        segment.content = content
        return segment, pos

    def _detect_case_sensitivity(self, pattern: str) -> bool:
        """Detect if pattern has (?-i) case sensitive flag."""
        return "(?-i)" in pattern

    def _calculate_prefix_lengths(self, segments: List[Segment]) -> None:
        """Calculate fixed prefix length for each segment."""
        prefix_length = 0

        for segment in segments:
            segment.prefix_length = prefix_length

            if isinstance(segment, FixedSegment):
                prefix_length += len(segment.content)
            elif isinstance(segment, GroupSegment):
                # For groups, calculate internal prefix lengths
                self._calculate_prefix_lengths(segment.content)
            elif isinstance(segment, OptionalSegment):
                # For optional segments, prefix length doesn't increase
                self._calculate_prefix_lengths(segment.content)
