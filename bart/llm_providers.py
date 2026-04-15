"""
LLM provider chain: Ollama (local, free) → Gemini (cloud fallback).
Both providers now support multi-turn conversation history so Bart
can maintain context across a session.

History format (shared):
    [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}, ...]
"""
import json
import os
import urllib.error
import urllib.request

import google.generativeai as genai


class ProviderError(Exception):
    pass


class OllamaProvider:
    def __init__(self):
        self.model = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
        self.host = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")

    def generate(self, system_prompt, history, user_prompt):
        messages = [{"role": "system", "content": system_prompt}]
        for turn in history:
            messages.append({"role": turn["role"], "content": turn["content"]})
        messages.append({"role": "user", "content": user_prompt})

        payload = {"model": self.model, "messages": messages, "stream": False}
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.host}/api/chat",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise ProviderError("Ollama is not running or is not installed.") from exc
        except TimeoutError as exc:
            raise ProviderError("Ollama timed out while generating a response.") from exc

        content = body.get("message", {}).get("content", "").strip()
        if not content:
            raise ProviderError("Ollama returned an empty response.")
        return content


class GeminiProvider:
    def __init__(self):
        self.model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            genai.configure(api_key=api_key)
        # Pass personality as a system instruction so it is always in scope.
        self._system_prompt_cache = None
        self._model_cache = None

    def _get_model(self, system_prompt):
        if self._system_prompt_cache != system_prompt or self._model_cache is None:
            self._model_cache = genai.GenerativeModel(
                model_name=self.model_name,
                system_instruction=system_prompt,
            )
            self._system_prompt_cache = system_prompt
        return self._model_cache

    def generate(self, system_prompt, history, user_prompt):
        model = self._get_model(system_prompt)
        # Convert shared history format → Gemini format ("assistant" → "model")
        gemini_history = [
            {"role": "model" if t["role"] == "assistant" else "user", "parts": [t["content"]]}
            for t in history
        ]
        chat = model.start_chat(history=gemini_history)
        response = chat.send_message(user_prompt)
        text = getattr(response, "text", "").strip()
        if not text:
            raise ProviderError("Gemini returned an empty response.")
        return text


class BrainProviderChain:
    def __init__(self):
        provider_names = os.getenv("BART_BRAIN_PROVIDERS", "ollama,gemini")
        self.providers = []
        for name in [n.strip().lower() for n in provider_names.split(",") if n.strip()]:
            if name == "ollama":
                self.providers.append(("ollama", OllamaProvider()))
            elif name == "gemini":
                self.providers.append(("gemini", GeminiProvider()))

    def generate(self, system_prompt, history, user_prompt):
        errors = []
        for name, provider in self.providers:
            try:
                return provider.generate(system_prompt, history, user_prompt)
            except Exception as exc:
                errors.append(f"{name}: {exc}")
        raise ProviderError(" | ".join(errors) if errors else "No providers configured.")
