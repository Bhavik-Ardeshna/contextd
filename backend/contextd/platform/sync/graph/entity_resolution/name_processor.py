"""Name processing utilities for entity resolution.

Extracts and normalizes names from various sources:
- Email addresses (jack.john@gmail.com → "Jack John")
- Raw names with various formats
- Usernames

This normalized form is stored in the graph for easier matching.
"""

import re
from typing import Optional

from .types import ProcessedName


class NameProcessor:
    """Extracts and normalizes names from various sources.

    Usage:
        processor = NameProcessor()

        # From email
        result = processor.process(email="jack.john@gmail.com")
        # → ProcessedName(normalized_name="jack john", display_name="Jack John", ...)

        # From raw name
        result = processor.process(name="Dr. John Smith Jr.")
        # → ProcessedName(normalized_name="john smith", display_name="John Smith", ...)
    """

    # Common email separators
    EMAIL_SEPARATORS = r'[._\-]'

    # Titles to remove
    TITLES = {
        'mr', 'mrs', 'ms', 'miss', 'dr', 'prof', 'professor',
        'sir', 'madam', 'mx', 'rev', 'fr', 'sr', 'jr',
    }

    # Suffixes to remove
    SUFFIXES = {
        'jr', 'sr', 'ii', 'iii', 'iv', 'phd', 'md', 'esq',
    }

    # System/generic email prefixes to skip
    SYSTEM_EMAIL_PREFIXES = {
        'noreply', 'no-reply', 'no_reply', 'support', 'admin',
        'info', 'hello', 'contact', 'help', 'sales', 'team',
        'notifications', 'alerts', 'system', 'mailer', 'daemon',
    }

    def process(
        self,
        name: Optional[str] = None,
        email: Optional[str] = None,
        username: Optional[str] = None,
    ) -> ProcessedName:
        """Process name from available sources.

        Priority:
        1. Raw name (if provided and not empty)
        2. Extract from email
        3. Extract from username
        4. Fallback to "Unknown"

        Args:
            name: Raw name string
            email: Email address
            username: Username

        Returns:
            ProcessedName with normalized fields
        """
        # Try raw name first
        if name and name.strip():
            return self._process_raw_name(name)

        # Try extracting from email
        if email and email.strip():
            extracted = self._extract_from_email(email)
            if extracted:
                return extracted

        # Try extracting from username
        if username and username.strip():
            return self._process_username(username)

        # Fallback
        return ProcessedName(
            normalized_name="unknown",
            display_name="Unknown",
            first_name=None,
            last_name=None,
            name_source="fallback",
            original_value=email or username or "",
        )

    def _process_raw_name(self, name: str) -> ProcessedName:
        """Process a raw name string."""
        original = name

        # Clean whitespace
        name = ' '.join(name.split())

        # Remove titles and suffixes
        name = self._remove_titles_suffixes(name)

        # Split into parts
        parts = name.split()

        first_name = parts[0] if parts else None
        last_name = parts[-1] if len(parts) > 1 else None

        # Normalize for storage (lowercase, no extra spaces)
        normalized = name.lower().strip()

        # Display name (proper case)
        display = self._to_title_case(name)

        return ProcessedName(
            normalized_name=normalized,
            display_name=display,
            first_name=self._to_title_case(first_name) if first_name else None,
            last_name=self._to_title_case(last_name) if last_name else None,
            name_source="raw",
            original_value=original,
        )

    def _extract_from_email(self, email: str) -> Optional[ProcessedName]:
        """Extract name from email address.

        Examples:
            jack.john@gmail.com → "Jack John"
            jack_smith@company.com → "Jack Smith"
            jsmith@corp.com → "Jsmith" (can't split further)
            john.doe.developer@gmail.com → "John Doe Developer"
        """
        original = email

        # Get local part (before @)
        if '@' not in email:
            return None

        local_part = email.split('@')[0].lower()

        # Skip if it looks like a system email
        if local_part in self.SYSTEM_EMAIL_PREFIXES:
            return None

        # Also skip if starts with common system prefixes
        for prefix in self.SYSTEM_EMAIL_PREFIXES:
            if local_part.startswith(prefix + '.') or local_part.startswith(prefix + '_'):
                return None

        # Split by common separators
        parts = re.split(self.EMAIL_SEPARATORS, local_part)

        # Filter out single chars, numbers, and very short parts
        name_parts = [
            p for p in parts
            if len(p) > 1 and not p.isdigit() and not p.isnumeric()
        ]

        # Also filter out common numeric suffixes attached to names
        cleaned_parts = []
        for p in name_parts:
            # Remove trailing numbers (e.g., "john123" → "john")
            cleaned = re.sub(r'\d+$', '', p)
            if len(cleaned) > 1:
                cleaned_parts.append(cleaned)

        if not cleaned_parts:
            # Fall back to original parts if cleaning removed everything
            cleaned_parts = name_parts if name_parts else [local_part]

        # Join parts
        extracted_name = ' '.join(cleaned_parts)

        if not extracted_name or extracted_name == "unknown":
            return None

        # Normalize
        normalized = extracted_name.lower()
        display = self._to_title_case(extracted_name)

        first_name = cleaned_parts[0] if cleaned_parts else None
        last_name = cleaned_parts[-1] if len(cleaned_parts) > 1 else None

        return ProcessedName(
            normalized_name=normalized,
            display_name=display,
            first_name=self._to_title_case(first_name) if first_name else None,
            last_name=self._to_title_case(last_name) if last_name else None,
            name_source="email",
            original_value=original,
        )

    def _process_username(self, username: str) -> ProcessedName:
        """Process a username into a name.

        Examples:
            jack_smith → "Jack Smith"
            JohnDoe → "John Doe" (camelCase)
            jsmith123 → "Jsmith" (remove numbers)
        """
        original = username

        # Remove numbers
        cleaned = re.sub(r'\d+', '', username)

        # Try to split camelCase
        # "JohnDoe" → "John Doe"
        camel_split = re.sub(r'([a-z])([A-Z])', r'\1 \2', cleaned)

        # Split by underscores, dashes, dots
        parts = re.split(r'[._\-\s]+', camel_split)

        # Filter empty parts
        name_parts = [p for p in parts if p and len(p) > 0]

        if not name_parts:
            name_parts = [cleaned] if cleaned else ["unknown"]

        extracted_name = ' '.join(name_parts)
        normalized = extracted_name.lower()
        display = self._to_title_case(extracted_name)

        first_name = name_parts[0] if name_parts else None
        last_name = name_parts[-1] if len(name_parts) > 1 else None

        return ProcessedName(
            normalized_name=normalized,
            display_name=display,
            first_name=self._to_title_case(first_name) if first_name else None,
            last_name=self._to_title_case(last_name) if last_name else None,
            name_source="username",
            original_value=original,
        )

    def _remove_titles_suffixes(self, name: str) -> str:
        """Remove common titles and suffixes from name."""
        parts = name.split()
        cleaned_parts = []

        for i, part in enumerate(parts):
            # Clean punctuation for comparison
            clean = re.sub(r'[.,]', '', part.lower())

            # Skip titles at start
            if i == 0 and clean in self.TITLES:
                continue

            # Skip suffixes at end
            if i == len(parts) - 1 and clean in self.SUFFIXES:
                continue

            # Skip if it's a title anywhere (Dr., Prof., etc.)
            if clean in self.TITLES:
                continue

            cleaned_parts.append(part)

        return ' '.join(cleaned_parts) if cleaned_parts else name

    def _to_title_case(self, text: Optional[str]) -> str:
        """Convert to title case, handling edge cases."""
        if not text:
            return ""

        # Handle all caps or all lower
        words = text.split()
        result = []

        for word in words:
            if word.isupper() or word.islower():
                result.append(word.capitalize())
            else:
                # Preserve existing mixed case (e.g., "McDonald")
                result.append(word)

        return ' '.join(result)


# Convenience function
def process_person_name(
    name: Optional[str] = None,
    email: Optional[str] = None,
    username: Optional[str] = None,
) -> ProcessedName:
    """Process a person's name from available data.

    Convenience function wrapping NameProcessor.

    Examples:
        >>> process_person_name(email="jack.smith@company.com")
        ProcessedName(normalized_name="jack smith", display_name="Jack Smith", ...)

        >>> process_person_name(name="Dr. John Smith Jr.")
        ProcessedName(normalized_name="john smith", display_name="John Smith", ...)
    """
    processor = NameProcessor()
    return processor.process(name=name, email=email, username=username)
