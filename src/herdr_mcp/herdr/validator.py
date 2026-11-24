"""The decoder for herdr's stdout and stderr JSON."""

from typing import TypeVar

from pydantic import BaseModel, ValidationError

from herdr_mcp.herdr.exceptions import HerdrError
from herdr_mcp.herdr.pydantic import ErrorResponse

ResponseModel = TypeVar("ResponseModel", bound=BaseModel)


def validate_response_json(
    model: type[ResponseModel], stdout: str, operation: str
) -> ResponseModel:
    try:
        return model.model_validate_json(stdout)
    except ValidationError as error:
        location = error.errors()[0]["loc"]
        field = ".".join(str(part) for part in location) or None
        raise HerdrError("unexpected_output", operation, 0, field) from None


def error_code_from_stderr(stderr: str) -> str:
    try:
        return ErrorResponse.model_validate_json(stderr).error.code
    except ValidationError:
        return "unreadable_error"
