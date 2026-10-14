"""Fuzzy matching utilities for entity resolution.

Provides functions for normalizing and comparing names/emails
using various similarity algorithms.
"""

from typing import Tuple

from contextd.platform.sync.semantic_merge.normalize_identity import (
    normalize_email as normalize_email,
)
from contextd.platform.sync.semantic_merge.normalize_identity import (
    normalize_name,
)


def levenshtein_ratio(s1: str, s2: str) -> float:
    """Calculate Levenshtein similarity ratio (0-1).

    Uses dynamic programming for efficiency.

    Args:
        s1: First string
        s2: Second string

    Returns:
        Similarity ratio between 0 and 1
    """
    if not s1 or not s2:
        return 0.0

    if s1 == s2:
        return 1.0

    len1, len2 = len(s1), len(s2)

    # Create distance matrix
    dp = [[0] * (len2 + 1) for _ in range(len1 + 1)]

    for i in range(len1 + 1):
        dp[i][0] = i
    for j in range(len2 + 1):
        dp[0][j] = j

    for i in range(1, len1 + 1):
        for j in range(1, len2 + 1):
            cost = 0 if s1[i-1] == s2[j-1] else 1
            dp[i][j] = min(
                dp[i-1][j] + 1,      # deletion
                dp[i][j-1] + 1,      # insertion
                dp[i-1][j-1] + cost  # substitution
            )

    distance = dp[len1][len2]
    max_len = max(len1, len2)

    return 1.0 - (distance / max_len)


def jaro_winkler_similarity(s1: str, s2: str) -> float:
    """Calculate Jaro-Winkler similarity (0-1).

    Better for short strings like names.
    Gives higher scores to strings with common prefixes.

    Args:
        s1: First string
        s2: Second string

    Returns:
        Similarity score between 0 and 1
    """
    if not s1 or not s2:
        return 0.0

    if s1 == s2:
        return 1.0

    len1, len2 = len(s1), len(s2)

    # Calculate match window
    match_distance = max(len1, len2) // 2 - 1
    if match_distance < 0:
        match_distance = 0

    s1_matches = [False] * len1
    s2_matches = [False] * len2

    matches = 0
    transpositions = 0

    # Find matches
    for i in range(len1):
        start = max(0, i - match_distance)
        end = min(i + match_distance + 1, len2)

        for j in range(start, end):
            if s2_matches[j] or s1[i] != s2[j]:
                continue
            s1_matches[i] = True
            s2_matches[j] = True
            matches += 1
            break

    if matches == 0:
        return 0.0

    # Count transpositions
    k = 0
    for i in range(len1):
        if not s1_matches[i]:
            continue
        while not s2_matches[k]:
            k += 1
        if s1[i] != s2[k]:
            transpositions += 1
        k += 1

    # Jaro similarity
    jaro = (
        matches / len1 +
        matches / len2 +
        (matches - transpositions // 2) / matches
    ) / 3

    # Jaro-Winkler: boost for common prefix (up to 4 chars)
    prefix_len = 0
    for i in range(min(4, len1, len2)):
        if s1[i] == s2[i]:
            prefix_len += 1
        else:
            break

    # Winkler modification: p = 0.1 (standard scaling factor)
    return jaro + prefix_len * 0.1 * (1 - jaro)


def compute_name_similarity(name1: str, name2: str) -> Tuple[float, str]:
    """Compute similarity between two names.

    Uses multiple strategies and returns the best score.

    Args:
        name1: First name
        name2: Second name

    Returns:
        Tuple of (score, method_used)
    """
    n1 = normalize_name(name1)
    n2 = normalize_name(name2)

    if not n1 or not n2:
        return 0.0, "empty"

    # Exact match after normalization
    if n1 == n2:
        return 1.0, "exact"

    # Try Jaro-Winkler (better for names)
    jw_score = jaro_winkler_similarity(n1, n2)
    best_score = jw_score
    best_method = "jaro_winkler"

    # Also try token-based matching for reordered names
    # "John Smith" vs "Smith, John"
    tokens1 = set(n1.split())
    tokens2 = set(n2.split())

    if tokens1 and tokens2:
        # Jaccard-like token overlap
        intersection = len(tokens1 & tokens2)
        union = len(tokens1 | tokens2)
        token_score = intersection / union if union > 0 else 0.0

        if token_score > best_score:
            best_score = token_score
            best_method = "token_overlap"

        # Check if all tokens from shorter name are in longer
        smaller, larger = (tokens1, tokens2) if len(tokens1) <= len(tokens2) else (tokens2, tokens1)
        if smaller and smaller.issubset(larger):
            subset_score = len(smaller) / len(larger)
            # Boost subset matches
            subset_score = min(1.0, subset_score + 0.2)
            if subset_score > best_score:
                best_score = subset_score
                best_method = "token_subset"

    return best_score, best_method


def names_are_similar(name1: str, name2: str, threshold: float = 0.8) -> bool:
    """Check if two names are similar enough to be considered the same person.

    Args:
        name1: First name
        name2: Second name
        threshold: Minimum similarity score (default 0.8)

    Returns:
        True if names are similar enough
    """
    score, _ = compute_name_similarity(name1, name2)
    return score >= threshold
