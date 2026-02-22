"""LLM — chat completions, token management, chat history."""

from typing import Any, Dict, List, Optional


class LLM:
    """LLM API: chat completions, token balance, chat sessions, models."""

    def __init__(self, client):
        self._c = client

    # ── Chat completions ─────────────────────────────────────────────

    def chat(
        self,
        model: str,
        message: str,
        *,
        role: str = "user",
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        presence_penalty: Optional[float] = None,
        timeout: int = 60,
    ) -> str:
        """Send a simple chat message and get response text.

        Args:
            model: Model identifier (e.g. "openai/gpt-oss-120b").
            message: Message content.
            role: Message role (default "user").
            max_tokens: Max tokens in response.
            temperature: Sampling temperature.
            top_p: Top-p sampling parameter.
            presence_penalty: Presence penalty.
            timeout: Request timeout in seconds (default 60).

        Returns:
            Response text content as string.
        """
        data = self.chat_completion(
            messages=[{"role": role, "content": message}],
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            presence_penalty=presence_penalty,
            timeout=timeout,
        )
        return data.get("content", "")

    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        *,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        presence_penalty: Optional[float] = None,
        timeout: int = 60,
    ) -> Dict[str, Any]:
        """Send a full chat completion request with message history.

        Args:
            messages: List of message dicts with "role" and "content" keys.
            model: Model identifier.
            max_tokens: Max tokens in response.
            temperature: Sampling temperature.
            top_p: Top-p sampling parameter.
            presence_penalty: Presence penalty.
            timeout: Request timeout in seconds.

        Returns:
            Full response data dict.
        """
        body: Dict[str, Any] = {"messages": messages}
        if model is not None:
            body["model"] = model
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if temperature is not None:
            body["temperature"] = temperature
        if top_p is not None:
            body["top_p"] = top_p
        if presence_penalty is not None:
            body["presence_penalty"] = presence_penalty
        return self._c.post("/llm/chat/completions", json=body, timeout=timeout)

    # ── Token balance & purchase ─────────────────────────────────────

    def balance(self) -> Dict[str, Any]:
        """Get current token balance."""
        return self._c.get("/llm/balance")

    def convert_rubles_to_tokens(self, ruble_amount: float, tokens_to_add: int) -> Any:
        """Convert rubles to LLM tokens."""
        return self._c.post("/llm/add-tokens", json={
            "ruble_amount": ruble_amount,
            "tokens_to_add": tokens_to_add,
        })

    def purchase_tokens(self, package_type: str) -> Any:
        """Purchase a token package.

        Args:
            package_type: "small", "medium", or "large".
        """
        return self._c.post("/llm/purchase", json={"package_type": package_type})

    # ── Models & packages ────────────────────────────────────────────

    def models(self) -> Any:
        """List available LLM models."""
        return self._c.get("/llm/models")

    def packages(self) -> Any:
        """List available token packages with pricing."""
        return self._c.get("/llm/packages")

    # ── Usage history ────────────────────────────────────────────────

    def usage_history(self, *, limit: int = 50, offset: int = 0) -> Any:
        """Get LLM usage history."""
        return self._c.get("/llm/usage/history", params={"limit": limit, "offset": offset})

    # ── Chat sessions ────────────────────────────────────────────────

    def create_chat_session(self, model: str, *, title: Optional[str] = None) -> Dict[str, Any]:
        """Create a persistent chat session."""
        body: Dict[str, Any] = {"model": model}
        if title is not None:
            body["title"] = title
        return self._c.post("/llm/chats", json=body)

    def list_chat_sessions(self, *, limit: int = 50, offset: int = 0) -> Any:
        """List your chat sessions."""
        return self._c.get("/llm/chats", params={"limit": limit, "offset": offset})

    def get_chat_session(self, chat_id: int) -> Dict[str, Any]:
        """Get a chat session with messages."""
        return self._c.get(f"/llm/chats/{chat_id}")

    def update_chat_session(self, chat_id: int, title: str) -> Dict[str, Any]:
        """Update chat session title."""
        return self._c.patch(f"/llm/chats/{chat_id}", json={"title": title})

    def delete_chat_session(self, chat_id: int) -> Any:
        """Delete a chat session."""
        return self._c.delete(f"/llm/chats/{chat_id}")

    def send_message(
        self,
        chat_id: int,
        message: str,
        *,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Send a message in a chat session.

        Args:
            chat_id: Chat session ID.
            message: Message text (1-10000 chars).
            model: Override model for this message.
            max_tokens: Max tokens in response.
            temperature: Sampling temperature.
        """
        body: Dict[str, Any] = {"message": message}
        if model is not None:
            body["model"] = model
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if temperature is not None:
            body["temperature"] = temperature
        return self._c.post(f"/llm/chats/{chat_id}/messages", json=body)

    # ── Terminal commands ────────────────────────────────────────────

    def generate_commands(
        self,
        prompt: str,
        *,
        context: Optional[Dict[str, Any]] = None,
        model: Optional[str] = None,
        max_commands: int = 5,
    ) -> Dict[str, Any]:
        """Generate terminal commands from natural language.

        Args:
            prompt: Natural language description of what to do.
            context: Additional context dict.
            model: LLM model to use.
            max_commands: Max commands to generate (1-10, default 5).
        """
        body: Dict[str, Any] = {"prompt": prompt, "max_commands": max_commands}
        if context is not None:
            body["context"] = context
        if model is not None:
            body["model"] = model
        return self._c.post("/llm/generate-commands", json=body)
