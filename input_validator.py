"""
Input validation module to prevent prompt injection attacks and ensure data integrity.
"""

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)


class InputValidationError(Exception):
    """Raised when input validation fails."""

    pass


class InputValidator:
    """Validates and sanitizes user input to prevent prompt injection attacks."""

    # Maximum allowed input lengths
    MAX_QUERY_LENGTH = 1000
    MAX_LOCATION_LENGTH = 100
    MAX_PRICE = 100000
    MIN_PRICE = 0

    # Dangerous patterns that indicate prompt injection attempts
    INJECTION_PATTERNS = [
        r"ignore\s+(previous|all|the)\s+instructions?",
        r"disregard\s+(previous|all|the)\s+instructions?",
        r"forget\s+(previous|all|the)\s+instructions?",
        r"system\s*:",
        r"assistant\s*:",
        r"user\s*:",
        r"\[system\]",
        r"\[assistant\]",
        r"\[user\]",
        r"<\|system\|>",
        r"<\|assistant\|>",
        r"<\|user\|>",
        r"###\s*system",
        r"###\s*assistant",
        r"###\s*user",
        r"---\s*system",
        r"---\s*assistant",
        r"---\s*user",
        r"you\s+are\s+now",
        r"act\s+as\s+(a|an)",
        r"pretend\s+to\s+be",
        r"roleplay\s+as",
        r"prompt\s*:",
        r"<prompt>",
        r"</prompt>",
        r"\{prompt\}",
        r"jailbreak",
        r"do\s+anything\s+now",
        r"DAN\s+mode",
    ]

    # Characters that could be used for injection
    SUSPICIOUS_CHARS = [
        "\x00",  # Null byte
        "\x01",
        "\x02",
        "\x03",
        "\x04",
        "\x05",
        "\x06",
        "\x07",
        "\x08",
        "\x0b",
        "\x0c",
        "\x0e",
        "\x0f",
    ]

    @classmethod
    def validate_user_query(cls, query: str) -> str:
        """
        Validate and sanitize a user query.

        Args:
            query: The user's travel query

        Returns:
            Sanitized query string

        Raises:
            InputValidationError: If validation fails
        """
        if not query:
            raise InputValidationError("Query cannot be empty")

        if not isinstance(query, str):
            raise InputValidationError("Query must be a string")

        # Check length
        if len(query) > cls.MAX_QUERY_LENGTH:
            logger.warning(
                f"Query exceeds maximum length: {len(query)} > {cls.MAX_QUERY_LENGTH}"
            )
            raise InputValidationError(
                f"Query too long. Maximum {cls.MAX_QUERY_LENGTH} characters allowed."
            )

        # Check for suspicious characters
        for char in cls.SUSPICIOUS_CHARS:
            if char in query:
                logger.warning(f"Suspicious character detected: {repr(char)}")
                raise InputValidationError("Invalid characters in query")

        # Check for prompt injection patterns
        query_lower = query.lower()
        for pattern in cls.INJECTION_PATTERNS:
            if re.search(pattern, query_lower, re.IGNORECASE):
                logger.warning(
                    f"Potential prompt injection detected: pattern '{pattern}' found in query"
                )
                raise InputValidationError(
                    "Invalid input detected. Please rephrase your query."
                )

        # Check for excessive special character usage (potential obfuscation)
        special_char_count = sum(
            1 for char in query if not char.isalnum() and not char.isspace()
        )
        special_char_ratio = special_char_count / len(query)
        if special_char_ratio > 0.3:  # More than 30% special characters
            logger.warning(f"Excessive special characters: {special_char_ratio:.2%}")
            raise InputValidationError(
                "Too many special characters. Please use normal text."
            )

        # Sanitize: strip whitespace and normalize spaces
        query = query.strip()
        query = re.sub(r"\s+", " ", query)

        return query

    @classmethod
    def validate_location(cls, location: Optional[str]) -> Optional[str]:
        """
        Validate and sanitize a location (airport code or city name).

        Args:
            location: Airport code or city name

        Returns:
            Sanitized location string or None

        Raises:
            InputValidationError: If validation fails
        """
        if not location:
            return None

        if not isinstance(location, str):
            raise InputValidationError("Location must be a string")

        # Check length
        if len(location) > cls.MAX_LOCATION_LENGTH:
            raise InputValidationError(
                f"Location too long. Maximum {cls.MAX_LOCATION_LENGTH} characters allowed."
            )

        # Remove whitespace
        location = location.strip()

        # Location should only contain letters, numbers, spaces, hyphens, and commas
        if not re.match(r"^[a-zA-Z0-9\s,\-]+$", location):
            raise InputValidationError(
                "Location contains invalid characters. Use only letters, numbers, spaces, hyphens, and commas."
            )

        return location

    @classmethod
    def validate_price(cls, price: Optional[float]) -> Optional[float]:
        """
        Validate a price value.

        Args:
            price: Maximum price value

        Returns:
            Validated price or None

        Raises:
            InputValidationError: If validation fails
        """
        if price is None:
            return None

        try:
            price = float(price)
        except (ValueError, TypeError):
            raise InputValidationError("Price must be a number")

        if price < cls.MIN_PRICE:
            raise InputValidationError("Price cannot be negative")

        if price > cls.MAX_PRICE:
            raise InputValidationError(
                f"Price too high. Maximum ${cls.MAX_PRICE:,.0f} allowed."
            )

        return price

    @classmethod
    def validate_date(cls, date_str: Optional[str]) -> Optional[str]:
        """
        Validate a date string (basic validation).

        Args:
            date_str: Date in YYYY-MM-DD format

        Returns:
            Validated date string or None

        Raises:
            InputValidationError: If validation fails
        """
        if not date_str:
            return None

        if not isinstance(date_str, str):
            raise InputValidationError("Date must be a string")

        # Basic YYYY-MM-DD format check
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
            raise InputValidationError(
                "Date must be in YYYY-MM-DD format (e.g., 2025-12-25)"
            )

        return date_str

    @classmethod
    def sanitize_for_display(cls, text: str, max_length: int = 500) -> str:
        """
        Sanitize text for safe display (e.g., in logs or UI).

        Args:
            text: Text to sanitize
            max_length: Maximum length to return

        Returns:
            Sanitized text
        """
        if not text:
            return ""

        # Truncate if too long
        if len(text) > max_length:
            text = text[:max_length] + "..."

        # Remove control characters
        text = "".join(char for char in text if char.isprintable() or char in "\n\r\t")

        return text


# Convenience function for quick validation
def validate_user_input(
    query: str,
    origin: Optional[str] = None,
    destination: Optional[str] = None,
    max_price: Optional[float] = None,
) -> dict:
    """
    Validate all user inputs at once.

    Args:
        query: User's travel query
        origin: Origin location
        destination: Destination location
        max_price: Maximum price

    Returns:
        Dictionary with validated inputs

    Raises:
        InputValidationError: If any validation fails
    """
    return {
        "query": InputValidator.validate_user_query(query),
        "origin": InputValidator.validate_location(origin),
        "destination": InputValidator.validate_location(destination),
        "max_price": InputValidator.validate_price(max_price),
    }
