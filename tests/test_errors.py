from unittest.mock import MagicMock

import pytest
from groq import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    RateLimitError,
)
from langchain_core.exceptions import OutputParserException

from recipe_agent.errors import InvalidIngredientAssessment, public_error_message


@pytest.mark.parametrize(
    "error, expected",
    [
        (
            InvalidIngredientAssessment("private ingredient details"),
            "inconsistent ingredient suggestions",
        ),
        (
            OutputParserException("private model response"),
            "inconsistent ingredient suggestions",
        ),
        (
            RateLimitError("private provider details", response=MagicMock(), body=None),
            "limit was reached",
        ),
        (
            AuthenticationError(
                "private provider details", response=MagicMock(), body=None
            ),
            "API credentials",
        ),
        (APIConnectionError(request=MagicMock()), "could not connect"),
        (APITimeoutError(request=MagicMock()), "too long"),
        (TimeoutError(), "too long"),
        (RuntimeError("private internal diagnostics"), "unexpected error"),
    ],
)
def test_errors_are_specific_and_do_not_expose_provider_payloads(error, expected):
    message = public_error_message(error)
    assert expected in message
    assert "private" not in message


def test_invalid_substitution_does_not_blame_configuration():
    message = public_error_message(InvalidIngredientAssessment("bad original"))
    assert "configuration" not in message and "credentials" not in message
