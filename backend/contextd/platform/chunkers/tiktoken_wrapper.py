"""Tiktoken wrapper that allows special tokens for Chonkie integration.

This module name intentionally contains 'tiktoken' (lowercase) so that Chonkie's
AutoTokenizer._get_backend() detects it as a tiktoken backend via the type string check:
    if "tiktoken" in str(type(self.tokenizer))

This ensures our encode() method (with allowed_special="all") is called.
"""

from typing import List, Sequence, Union


class TiktokenWrapperForChonkie:
    """Wrapper for tiktoken Encoding that allows special tokens.

    Chonkie's AutoTokenizer wraps tiktoken but doesn't pass allowed_special="all"
    when encoding. This causes failures when text contains special tokens like
    <|endoftext|> (common in AI-generated code or discussions about LLMs).

    By placing this wrapper in a module with "tiktoken" in the path, Chonkie's
    AutoTokenizer detects it as "tiktoken" backend and calls our encode() method
    directly, which properly handles special tokens with allowed_special="all".
    """

    def __init__(self, tiktoken_encoding):
        """Initialize with a tiktoken Encoding object.

        Args:
            tiktoken_encoding: A tiktoken.Encoding instance (e.g., cl100k_base)
        """
        self._encoding = tiktoken_encoding

    def __repr__(self) -> str:
        """Return a string representation of the tokenizer."""
        return f"TiktokenWrapperForChonkie(encoding={self._encoding.name})"

    def encode(self, text: str) -> Sequence[int]:
        """Encode text to token IDs, allowing all special tokens.

        Args:
            text: The text to encode

        Returns:
            Sequence of token IDs
        """
        return self._encoding.encode(text, allowed_special="all")

    def encode_batch(self, texts: List[str]) -> List[List[int]]:
        """Encode multiple texts to token IDs, allowing all special tokens.

        Args:
            texts: List of texts to encode

        Returns:
            List of token ID sequences
        """
        return [self._encoding.encode(text, allowed_special="all") for text in texts]

    def decode(self, tokens: Sequence[int]) -> str:
        """Decode token IDs back to text.

        Args:
            tokens: Sequence of token IDs

        Returns:
            Decoded text string
        """
        return self._encoding.decode(list(tokens))

    def decode_batch(self, token_lists: List[List[int]]) -> List[str]:
        """Decode multiple token sequences back to text.

        Args:
            token_lists: List of token ID sequences

        Returns:
            List of decoded text strings
        """
        return [self._encoding.decode(tokens) for tokens in token_lists]

    def tokenize(self, text: str) -> Sequence[Union[str, int]]:
        """Tokenize text into token IDs.

        Args:
            text: The text to tokenize

        Returns:
            Sequence of token IDs
        """
        return self.encode(text)

    def count_tokens(self, text: str) -> int:
        """Count the number of tokens in text.

        Args:
            text: The text to count tokens in

        Returns:
            Number of tokens
        """
        return len(self.encode(text))
