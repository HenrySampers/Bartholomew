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

    def generate(self, system_prompt, user_prompt):
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
        }
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

        message = body.get("message", {})
        content = message.get("content", "").strip()
        if not content:
            raise ProviderError("Ollama returned an empty response.")
        return content


class GeminiProvider:
    def __init__(self):
        self.model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(model_name=self.model_name)

    def generate(self, system_prompt, user_prompt):
        prompt = f"{system_prompt}\n\n{user_prompt}"
        response = self.model.generate_content(prompt)
        text = getattr(response, "text", "").strip()
        if not text:
            raise ProviderError("Gemini returned an empty response.")
        return text


class BrainProviderChain:
    def __init__(self):
        provider_names = os.getenv("BART_BRAIN_PROVIDERS", "ollama,gemini")
        self.providers = []
        for name in [item.strip().lower() for item in provider_names.split(",") if item.strip()]:
            if name == "ollama":
                self.providers.append(("ollama", OllamaProvider()))
            elif name == "gemini":
                self.providers.append(("gemini", GeminiProvider()))

    def generate(self, system_prompt, user_prompt):
        errors = []
        for name, provider in self.providers:
            try:
                return provider.generate(system_prompt, user_prompt)
            except Exception as exc:
                errors.append(f"{name}: {exc}")
        joined = " | ".join(errors) if errors else "No providers configured."
        raise ProviderError(joined)
