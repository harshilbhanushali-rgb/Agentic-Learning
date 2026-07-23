from __future__ import annotations
import json
import time


class GemmaError(Exception):
    pass


def call_gemma(
    prompt: str,
    api_key: str,
    *,
    model: str = "gemma-4-31b-it",
    temperature: float = 0.2,
    max_output_tokens: int = 8192,
    max_retries: int = 5,
) -> dict:
    """Call Gemma via Google AI Studio. Forces JSON output. Retries on 429/503."""
    from google import genai
    from google.genai import types

    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=180_000),  # 3-minute HTTP timeout
    )

    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                ),
            )
            text = response.text.strip()
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise GemmaError(f"Gemma returned non-JSON: {e}\nRaw: {text[:500]}")
        except Exception as e:
            err_str = str(e).lower()
            retryable = any(code in err_str for code in
                            ["429", "500", "503", "504", "rate", "disconnect", "remote protocol",
                             "connection", "timeout", "timed out", "deadline", "unavailable", "internal"])
            if attempt < max_retries - 1 and retryable:
                wait = 2 ** (attempt + 1)
                print(f"[gemma] Transient error (attempt {attempt+1}). Waiting {wait}s...")
                time.sleep(wait)
                continue
            raise GemmaError(f"Gemma API error: {e}") from e

    raise GemmaError("Max retries exceeded")
