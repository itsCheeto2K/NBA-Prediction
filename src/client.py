import hashlib
import json
import logging
import random
import threading
import time
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional, Type

from src.config import settings

logger = logging.getLogger(__name__)


class CircuitState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreakerOpenException(Exception):
    """Raised when request is attempted while circuit breaker is OPEN."""
    pass


class CircuitBreaker:
    """
    Circuit breaker for external HTTP APIs (§4):
    - Opens after consecutive_failures >= failure_threshold (default 3) or explicit 429/403.
    - Cooldown period: minimum cooldown_seconds (default 600s / 10 min).
    - Half-open state: allows 1 probe request after cooldown.
      If probe succeeds -> CLOSED; if probe fails -> OPEN with renewed cooldown.
    """
    def __init__(
        self,
        failure_threshold: int = 3,
        cooldown_seconds: float = 600.0,
    ):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.state = CircuitState.CLOSED
        self.consecutive_failures = 0
        self.last_failure_time: Optional[float] = None
        self.cooldown_until: Optional[float] = None
        self._lock = threading.Lock()

    def record_success(self) -> None:
        with self._lock:
            self.consecutive_failures = 0
            self.state = CircuitState.CLOSED
            self.cooldown_until = None

    def record_failure(self, is_fatal: bool = False, retry_after: Optional[float] = None) -> None:
        with self._lock:
            self.consecutive_failures += 1
            now = time.time()
            self.last_failure_time = now
            cooldown = max(self.cooldown_seconds, retry_after or 0.0)

            if is_fatal or self.consecutive_failures >= self.failure_threshold:
                self.state = CircuitState.OPEN
                self.cooldown_until = now + cooldown
                logger.warning(
                    f"CircuitBreaker OPENED! Consecutive failures: {self.consecutive_failures}. "
                    f"Cooldown for {cooldown:.1f}s until {datetime.fromtimestamp(self.cooldown_until, tz=timezone.utc).isoformat()}"
                )

    def can_execute(self) -> bool:
        with self._lock:
            if self.state == CircuitState.CLOSED:
                return True
            now = time.time()
            if self.state == CircuitState.OPEN:
                if self.cooldown_until and now >= self.cooldown_until:
                    self.state = CircuitState.HALF_OPEN
                    logger.info("CircuitBreaker transitioning to HALF_OPEN for test probe.")
                    return True
                return False
            if self.state == CircuitState.HALF_OPEN:
                return True
            return False

    def check_and_guard(self) -> None:
        if not self.can_execute():
            remaining = (self.cooldown_until - time.time()) if self.cooldown_until else 0.0
            raise CircuitBreakerOpenException(
                f"Circuit breaker is OPEN. Cooldown active for {max(0.0, remaining):.1f} more seconds. "
                "Requests blocked to prevent provider throttling/bans."
            )


class GlobalRateLimiter:
    """Thread-safe global rate limiter ensuring minimum interval between request starts."""
    def __init__(self, min_interval: float = 1.0):
        self.min_interval = min_interval
        self.last_start_time = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = time.time()
            elapsed = now - self.last_start_time
            if elapsed < self.min_interval:
                sleep_time = self.min_interval - elapsed
                time.sleep(sleep_time)
            self.last_start_time = time.time()


# Singleton rate limiter and circuit breaker across NBAClient instances
_GLOBAL_RATE_LIMITER = GlobalRateLimiter(min_interval=1.0)
_GLOBAL_CIRCUIT_BREAKER = CircuitBreaker(failure_threshold=3, cooldown_seconds=600.0)


class NBAClient:
    """
    Robust wrapper around nba_api endpoints with caching, global rate-limiting,
    exponential backoff with jitter, and circuit breaker (§4).
    """
    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        request_delay: float = 1.0,
        connect_timeout: int = 10,
        read_timeout: int = 30,
        max_attempts: int = 3,
        circuit_breaker: Optional[CircuitBreaker] = None,
        rate_limiter: Optional[GlobalRateLimiter] = None,
    ):
        self.cache_dir = cache_dir or settings.RAW_DIR
        self.request_delay = max(request_delay, 1.0)
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self.timeout = read_timeout  # for endpoints taking a single timeout
        self.max_attempts = max_attempts
        self.circuit_breaker = circuit_breaker or _GLOBAL_CIRCUIT_BREAKER
        self.rate_limiter = rate_limiter or _GLOBAL_RATE_LIMITER
        self.last_request_time: float = 0.0
        
        # Ensure cache directory exists
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _apply_rate_limit(self) -> None:
        """Enforce polite pause between consecutive requests (§4)."""
        now = time.time()
        elapsed = now - self.last_request_time
        if elapsed < self.request_delay:
            time.sleep(self.request_delay - elapsed)
        self.last_request_time = time.time()

    def _generate_cache_key(self, endpoint: str, params: Dict[str, Any]) -> str:
        """Create a deterministic hash string for an endpoint and parameter set."""
        normalized = {k: str(v) for k, v in sorted(params.items())}
        param_str = json.dumps(normalized, sort_keys=True)
        return hashlib.sha256(f"{endpoint}:{param_str}".encode("utf-8")).hexdigest()

    def _get_cache_path(self, endpoint: str, params: Dict[str, Any]) -> Path:
        endpoint_dir = self.cache_dir / endpoint.lower()
        endpoint_dir.mkdir(parents=True, exist_ok=True)
        cache_key = self._generate_cache_key(endpoint, params)
        return endpoint_dir / f"{cache_key}.json"

    def save_raw_cache(self, endpoint: str, params: Dict[str, Any], raw_content: str) -> Path:
        """Store raw response string and audit metadata in disk cache."""
        cache_path = self._get_cache_path(endpoint, params)
        content_hash = hashlib.sha256(raw_content.encode("utf-8")).hexdigest()
        
        payload = {
            "endpoint": endpoint,
            "params": params,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "sha256_hash": content_hash,
            "raw_response": raw_content,
        }
        
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            
        return cache_path

    def load_raw_cache(self, endpoint: str, params: Dict[str, Any]) -> Optional[str]:
        """Load raw response string from disk cache if present."""
        cache_path = self._get_cache_path(endpoint, params)
        if cache_path.exists():
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return data.get("raw_response")
            except Exception as e:
                logger.warning(f"Failed to load cache from {cache_path}: {e}")
        return None

    def execute(
        self,
        endpoint_cls: Type[Any],
        params: Optional[Dict[str, Any]] = None,
        use_cache: bool = True,
    ) -> Any:
        """
        Execute an nba_api endpoint with circuit breaker check, cache check,
        global rate limiting, and 3-attempt backoff with jitter (§4).
        """
        params = params or {}
        endpoint_name = endpoint_cls.__name__.lower()
        
        # 1. Check disk cache first (bypasses network & rate limits)
        if use_cache:
            cached_raw = self.load_raw_cache(endpoint_name, params)
            if cached_raw:
                logger.info(f"Loading {endpoint_name} from cache with params: {params}")
                instance = endpoint_cls(**params, get_request=False)
                try:
                    from nba_api.stats.library.http import NBAStatsResponse
                    instance.nba_response = NBAStatsResponse(
                        response=cached_raw,
                        status_code=200,
                        url="",
                    )
                    instance.load_response()
                    return instance
                except Exception as e:
                    logger.warning(f"Failed to load cached response for {endpoint_name}: {e}. Refetching...")

        # 2. Check circuit breaker before hitting network
        self.circuit_breaker.check_and_guard()

        # 3. Retry schedule: max 3 attempts total (backoffs: 2.0s before attempt 2, 5.0s before attempt 3)
        backoff_schedule = [0.0, 2.0, 5.0]
        last_exception = None

        for attempt_idx in range(self.max_attempts):
            attempt_num = attempt_idx + 1
            if attempt_idx > 0:
                base_delay = backoff_schedule[min(attempt_idx, len(backoff_schedule) - 1)]
                jitter = random.uniform(0.0, 0.5)
                wait_time = base_delay + jitter
                logger.info(f"Retrying {endpoint_name} (attempt {attempt_num}/{self.max_attempts}) in {wait_time:.2f}s...")
                time.sleep(wait_time)

            # Global rate limiting across threads/instances
            self.rate_limiter.wait()

            try:
                logger.info(f"Requesting {endpoint_name} (attempt {attempt_num}) with params: {params}")
                instance = endpoint_cls(
                    **params,
                    timeout=self.timeout,
                    get_request=False
                )
                instance.get_request()
                raw_response = instance.get_response()

                # Success -> record in circuit breaker
                self.circuit_breaker.record_success()

                if use_cache and raw_response:
                    self.save_raw_cache(endpoint_name, params, raw_response)

                return instance

            except Exception as e:
                last_exception = e
                err_str = str(e).lower()
                is_fatal = "429" in err_str or "403" in err_str or "block" in err_str
                
                # Check for Retry-After header or info if accessible
                retry_after = None
                if is_fatal:
                    logger.error(f"Fatal HTTP status detected for {endpoint_name}: {e}. Tripping circuit breaker.")
                    self.circuit_breaker.record_failure(is_fatal=True, retry_after=600.0)
                    raise RuntimeError(f"Circuit breaker tripped due to fatal HTTP response: {e}") from e

                # Record transient failure
                self.circuit_breaker.record_failure(is_fatal=False)
                logger.warning(
                    f"Attempt {attempt_num}/{self.max_attempts} failed for {endpoint_name}: {e}"
                )

        # All attempts exhausted
        raise RuntimeError(
            f"Failed to fetch {endpoint_name} after {self.max_attempts} attempts: {last_exception}"
        ) from last_exception
