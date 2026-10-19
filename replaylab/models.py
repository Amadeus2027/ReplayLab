"""One protocol shared by the compiler, editor, executor and skill exporter."""

from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator


def origin(url: str) -> str:
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ValueError("Only HTTP(S) URLs without embedded credentials are supported")
    port = parsed.port
    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    suffix = (
        f":{port}" if port is not None and port != {"http": 80, "https": 443}[parsed.scheme] else ""
    )
    return f"{parsed.scheme}://{host}{suffix}"


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Frame(Model):
    id: str
    timestamp_ms: int = Field(ge=0)
    path: str


class Evidence(Model):
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    frame_ids: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def ordered(self):
        if self.end_ms < self.start_ms:
            raise ValueError("Evidence end must follow start")
        return self


class Target(Model):
    description: str = Field(min_length=1)
    strategy: Literal["role", "label", "text", "placeholder"]
    value: str = Field(min_length=1)
    role: str | None = None

    @model_validator(mode="after")
    def role_required(self):
        if self.strategy == "role" and not self.role:
            raise ValueError("Role targets need an accessibility role")
        return self


class Assertion(Model):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "allOf": [
                {
                    "if": {
                        "properties": {"type": {"enum": ["visible", "text", "value", "checked"]}}
                    },
                    "then": {"required": ["target"], "properties": {"target": {"type": "object"}}},
                },
                {
                    "if": {"properties": {"type": {"enum": ["text", "url", "value"]}}},
                    "then": {
                        "required": ["expected"],
                        "properties": {"expected": {"type": "string"}},
                    },
                },
            ]
        },
    )
    type: Literal["visible", "text", "url", "value", "checked"]
    target: Target | None = None
    expected: str | None = None

    @model_validator(mode="after")
    def required_fields(self):
        if self.type != "url" and self.target is None:
            raise ValueError("Element assertions need a target")
        if self.type in {"text", "url", "value"} and self.expected is None:
            raise ValueError("Text and URL assertions need an expected value")
        return self


class Step(Model):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    action: Literal["click", "fill", "select", "check", "press", "navigate"]
    description: str = Field(min_length=1)
    source: Evidence
    target: Target | None = None
    value: str | None = None
    confidence: float = Field(ge=0, le=1)
    status: Literal["needs_review", "approved"] = "needs_review"
    sensitive: bool = False
    verification: Assertion

    @model_validator(mode="after")
    def action_fields(self):
        if self.action != "navigate" and self.target is None:
            raise ValueError("This action needs a target")
        if self.action in {"fill", "select", "press", "navigate"} and self.value is None:
            raise ValueError("This action needs a value; unknown inputs must use ${parameter}")
        if self.action == "press" and self.value not in {
            "Enter",
            "Tab",
            "Escape",
            "ArrowDown",
            "ArrowUp",
        }:
            raise ValueError("Unsupported key")
        return self


class Workflow(Model):
    schema_version: Literal["0.1"] = "0.1"
    title: str = Field(min_length=1)
    start_url: str
    allowed_origins: list[str] = Field(min_length=1)
    parameters: dict[str, str] = Field(default_factory=dict)
    preconditions: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    steps: list[Step] = Field(min_length=1, max_length=50)
    postconditions: list[Assertion] = Field(min_length=1)

    @model_validator(mode="after")
    def consistency(self):
        normalized = [origin(value) for value in self.allowed_origins]
        if self.allowed_origins != normalized:
            raise ValueError("allowed_origins must contain normalized origins without paths")
        if origin(self.start_url) not in normalized:
            raise ValueError("Start URL must belong to an allowed origin")
        ids = [step.id for step in self.steps]
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate step IDs")
        return self
