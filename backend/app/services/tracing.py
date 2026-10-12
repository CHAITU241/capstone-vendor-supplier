from contextlib import contextmanager, ExitStack, nullcontext
from functools import lru_cache
import hashlib
import logging
from typing import Any, Iterator

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


class _NoopObservation:
    def update(self, **_: Any) -> None:
        return None

    def update_trace(self, **_: Any) -> None:
        return None

    def score_trace(self, **_: Any) -> None:
        return None


class _SafeObservation:
    """Keep telemetry failures from changing application behavior."""

    def __init__(self, observation: Any):
        self.observation = observation

    def update(self, **kwargs: Any) -> None:
        try:
            self.observation.update(**kwargs)
        except Exception:  # pragma: no cover - SDK/network-specific failure
            logger.debug("Langfuse observation update failed.", exc_info=True)

    def update_trace(self, **kwargs: Any) -> None:
        try:
            updater = getattr(self.observation, "update_trace", None)
            if updater is not None:
                updater(**kwargs)
        except Exception:  # pragma: no cover - SDK/network-specific failure
            logger.debug("Langfuse trace update failed.", exc_info=True)

    def score_trace(self, **kwargs: Any) -> None:
        try:
            scorer = getattr(self.observation, "score_trace", None)
            if scorer is not None:
                scorer(**kwargs)
        except Exception:  # pragma: no cover - SDK/network-specific failure
            logger.debug("Langfuse trace scoring failed.", exc_info=True)


def telemetry_subject_id(value: Any) -> str:
    """Return a stable, non-reversible label suitable for telemetry grouping."""

    digest = hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:12]
    return f"supplier-{digest}"


class LangfuseTracer:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.capture_content = settings.langfuse_capture_content
        self.client: Any | None = None
        self.propagate_attributes: Any | None = None

        secret_key = (
            settings.langfuse_secret_key.get_secret_value()
            if settings.langfuse_secret_key
            else ""
        )
        if not settings.langfuse_enabled or not settings.langfuse_public_key or not secret_key:
            return

        try:
            from langfuse import Langfuse, propagate_attributes

            self.client = Langfuse(
                public_key=settings.langfuse_public_key,
                secret_key=secret_key,
                base_url=settings.langfuse_base_url,
                environment=settings.app_env,
                release=settings.langfuse_release,
                tracing_enabled=True,
            )
            self.propagate_attributes = propagate_attributes
        except Exception:  # pragma: no cover - SDK initialization failure
            logger.warning("Langfuse tracing could not be initialized; continuing without tracing.")

    def input_payload(self, metadata: dict[str, Any], content: Any = None) -> dict[str, Any]:
        if not self.capture_content:
            return metadata
        return {"metadata": metadata, "content": content}

    def model_name(self, provider_model: str) -> str:
        """Use canonical model names so Langfuse can match its pricing catalog.

        OpenRouter identifies models as ``vendor/model`` while Langfuse's built-in
        pricing definitions generally use the canonical model portion. The full
        provider model remains attached as metadata on every generation.
        """

        if self.settings.ai_provider == "openrouter" and "/" in provider_model:
            return provider_model.split("/", 1)[1]
        return provider_model

    @contextmanager
    def trace(
        self,
        *,
        name: str,
        input_data: dict[str, Any],
        metadata: dict[str, Any] | None = None,
        subject_id: str | None = None,
        session_id: str | None = None,
        tags: list[str] | None = None,
    ) -> Iterator[_SafeObservation | _NoopObservation]:
        """Create a parent span so generations form one inspectable workflow."""

        if self.client is None:
            yield _NoopObservation()
            return
        propagation = (
            self.propagate_attributes(
                user_id=subject_id,
                session_id=session_id,
                metadata=metadata or {},
                version=self.settings.langfuse_release,
                tags=tags or [],
                trace_name=name,
            )
            if self.propagate_attributes else nullcontext()
        )
        stack = ExitStack()
        try:
            stack.enter_context(propagation)
            observation_context = self.client.start_as_current_observation(
                as_type="span",
                name=name,
                input=input_data,
                metadata=metadata or {},
                version=self.settings.langfuse_release,
            )
            observation = stack.enter_context(observation_context)
        except Exception:  # pragma: no cover - SDK initialization failure
            stack.close()
            logger.debug("Langfuse trace could not be started.", exc_info=True)
            yield _NoopObservation()
            return
        with stack:
            yield _SafeObservation(observation)

    @contextmanager
    def generation(
        self,
        *,
        name: str,
        model: str,
        input_data: dict[str, Any],
        metadata: dict[str, Any] | None = None,
        observation_type: str = "generation",
    ) -> Iterator[_SafeObservation | _NoopObservation]:
        if self.client is None:
            yield _NoopObservation()
            return

        try:
            observation_context = self.client.start_as_current_observation(
                as_type=observation_type,
                name=name,
                model=self.model_name(model),
                input=input_data,
                metadata={
                    "provider": self.settings.ai_provider,
                    "provider_model": model,
                    **(metadata or {}),
                },
                version=self.settings.langfuse_release,
            )
        except Exception:  # pragma: no cover - SDK initialization failure
            logger.debug("Langfuse generation could not be started.", exc_info=True)
            yield _NoopObservation()
            return

        with observation_context as observation:
            safe = _SafeObservation(observation)
            yield safe

    def flush(self) -> None:
        if self.client is None:
            return
        try:
            self.client.flush()
        except Exception:  # pragma: no cover - SDK/network-specific failure
            logger.debug("Langfuse flush failed.", exc_info=True)


@lru_cache
def get_langfuse_tracer() -> LangfuseTracer:
    return LangfuseTracer(get_settings())
