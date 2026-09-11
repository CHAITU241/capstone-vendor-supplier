from contextlib import contextmanager
from functools import lru_cache
import logging
from typing import Any, Iterator

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


class _NoopObservation:
    def update(self, **_: Any) -> None:
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


class LangfuseTracer:
    def __init__(self, settings: Settings):
        self.capture_content = settings.langfuse_capture_content
        self.client: Any | None = None

        secret_key = (
            settings.langfuse_secret_key.get_secret_value()
            if settings.langfuse_secret_key
            else ""
        )
        if not settings.langfuse_enabled or not settings.langfuse_public_key or not secret_key:
            return

        try:
            from langfuse import Langfuse

            self.client = Langfuse(
                public_key=settings.langfuse_public_key,
                secret_key=secret_key,
                base_url=settings.langfuse_base_url,
                environment=settings.app_env,
                release=settings.langfuse_release,
                tracing_enabled=True,
            )
        except Exception:  # pragma: no cover - SDK initialization failure
            logger.warning("Langfuse tracing could not be initialized; continuing without tracing.")

    def input_payload(self, metadata: dict[str, Any], content: Any = None) -> dict[str, Any]:
        if not self.capture_content:
            return metadata
        return {"metadata": metadata, "content": content}

    @contextmanager
    def generation(
        self,
        *,
        name: str,
        model: str,
        input_data: dict[str, Any],
    ) -> Iterator[_SafeObservation | _NoopObservation]:
        if self.client is None:
            yield _NoopObservation()
            return

        try:
            observation_context = self.client.start_as_current_observation(
                as_type="generation",
                name=name,
                model=model,
                input=input_data,
            )
        except Exception:  # pragma: no cover - SDK initialization failure
            logger.debug("Langfuse generation could not be started.", exc_info=True)
            yield _NoopObservation()
            return

        with observation_context as observation:
            yield _SafeObservation(observation)

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
