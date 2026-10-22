"""Which model each agent uses: Claude through the Anthropic API, or a local script in mock mode.

Mock mode exists so you can run and test the whole pipeline without an API key. The scripts are deliberately
simple keyword rules; they show the flow, not what a real model would say.
"""

import json
from typing import AsyncGenerator, Callable

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from support_agent import config

Script = Callable[[LlmRequest], types.Part]


class ScriptedLlm(BaseLlm):
    """A stand-in model: `script` decides each reply (text or a tool call) from the request."""

    script: Script

    async def generate_content_async(self, llm_request: LlmRequest, stream: bool = False) -> AsyncGenerator[LlmResponse, None]:
        part = self.script(llm_request)
        yield LlmResponse(
            content=types.Content(role="model", parts=[part]),
            usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=0, candidates_token_count=0),
        )


def real_model() -> BaseLlm | str:
    # A "claude-..." model name makes ADK call Claude through the Anthropic API with ANTHROPIC_API_KEY.
    return config.MODEL


def model_for(script: Script) -> BaseLlm | str:
    return ScriptedLlm(model="mock", script=script) if config.mock_mode() else real_model()


# ---------- helpers for scripts ----------


def last_user_text(req: LlmRequest) -> str:
    for content in reversed(req.contents):
        if content.role == "user":
            texts = [p.text for p in content.parts or [] if p.text]
            if texts:
                return "\n".join(texts)
    return ""


def last_tool_result(req: LlmRequest) -> types.FunctionResponse | None:
    """The tool result the model is being asked to read, if the latest turn is one."""
    if not req.contents:
        return None
    for part in req.contents[-1].parts or []:
        if part.function_response:
            return part.function_response
    return None


def tool_payload(response: dict | None) -> dict:
    """A tool's own result. MCP tools return {"content": [{"type": "text", "text": "<json>"}]}; a result from a
    before-tool callback is already a plain dict."""
    response = response or {}
    content = response.get("content")
    if isinstance(content, list) and content and content[0].get("type") == "text":
        try:
            return json.loads(content[0]["text"])
        except json.JSONDecodeError:
            return {"text": content[0]["text"]}
    return response


def tool_names(req: LlmRequest) -> set[str]:
    return set(req.tools_dict)


def text(t: str) -> types.Part:
    return types.Part(text=t)


def call(name: str, **args) -> types.Part:
    return types.Part(function_call=types.FunctionCall(id=f"mock-{name}", name=name, args=args))
