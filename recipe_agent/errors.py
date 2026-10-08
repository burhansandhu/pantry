from groq import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    RateLimitError,
)
from langchain_core.exceptions import OutputParserException
from pydantic import ValidationError


class InvalidIngredientAssessment(ValueError):
    """A structured assessment violated an ingredient workflow constraint."""


def public_error_message(error: Exception) -> str:
    """Expose useful failure categories without provider payloads or secrets."""
    if isinstance(error, RateLimitError):
        return "Groq's request or token limit was reached. Please wait a little, then start a new recipe."
    if isinstance(error, AuthenticationError):
        return "Groq rejected the API credentials. Check GROQ_API_KEY in the backend .env file."
    if isinstance(error, (APITimeoutError, TimeoutError)):
        return "The recipe assistant took too long to respond. Please start a new recipe to retry."
    if isinstance(error, APIConnectionError):
        return "The backend could not connect to Groq. Check the connection and start a new recipe to retry."
    if isinstance(
        error, (InvalidIngredientAssessment, OutputParserException, ValidationError)
    ):
        return "The assistant returned inconsistent ingredient suggestions after retrying. Please start a new recipe with your ingredient list."
    return "The recipe assistant encountered an unexpected error. Please start a new recipe to retry."
