"""
ActronAir Neo API client.

Provides the main API client for communicating with the ActronAir Neo
cloud service, including rate limiting, response caching, and request
deduplication.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

import aiohttp
from pydantic import ValidationError

from custom_components.actronair_neo.exceptions import (
    ActronAirNeoError,
    ApiError,
    AuthenticationError,
    DeviceOfflineError,
    RateLimitError,
)

from .const import (
    API_TIMEOUT,
    API_URL,
    API_URL_QUE,
    DEFAULT_CACHE_TTL,
    ENDPOINT_AC_COMMANDS,
    ENDPOINT_AC_STATUS,
    ENDPOINT_AC_SYSTEMS,
    ENDPOINT_ACCOUNT,
    ENDPOINT_REALTIME_DETAILS,
    HEALTH_PROBE_COOLDOWN,
    MAX_REQUESTS_PER_MINUTE,
    MAX_RETRIES,
    MIN_FAN_MODE_INTERVAL,
    RETRYABLE_STATUS_CODES,
    SYSTEM_TYPE_NXGEN,
)
from .models import (
    ActronAirUserInfo,
    CommandData,
    DeviceInfo,
    FanModeType,
    HvacModeType,
    ZoneCapabilities,
)
from .push.merge import loads_repairing_escapes
from .push.models import RealtimeConnectionDetails

if TYPE_CHECKING:
    from .auth import ActronAirNeoAuth

_LOGGER = logging.getLogger(__name__)


def _now_matching(reference: datetime | None = None) -> datetime:
    """Return current datetime matching tz-awareness of reference (defaults to UTC)."""
    if reference is not None and reference.tzinfo is None:
        return datetime.now()  # noqa: DTZ005
    return datetime.now(UTC)


class RateLimiter:
    """Rate limiter to prevent overwhelming the API."""

    def __init__(self, calls_per_minute: int) -> None:
        """Initialize the rate limiter."""
        self.calls_per_minute = calls_per_minute
        self.semaphore = asyncio.Semaphore(calls_per_minute)
        self.call_times: list[datetime] = []

    async def __aenter__(self) -> None:
        """Enter the rate limiter context."""
        await self.acquire()

    async def __aexit__(self, *_: object) -> None:
        """Exit the rate limiter context."""
        self.release()

    async def acquire(self) -> None:
        """Acquire a slot for making an API call."""
        await self.semaphore.acquire()
        self.call_times = [
            t for t in self.call_times if _now_matching(t) - t < timedelta(minutes=1)
        ]
        if len(self.call_times) >= self.calls_per_minute:
            first = self.call_times[0]
            sleep_time = 60 - (_now_matching(first) - first).total_seconds()
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
            self.call_times = [
                t
                for t in self.call_times
                if _now_matching(t) - t < timedelta(minutes=1)
            ]
        self.call_times.append(datetime.now(UTC))

    def release(self) -> None:
        """Release the acquired slot."""
        self.semaphore.release()


class ResponseCache:
    """Response cache with TTL for API optimization."""

    def __init__(
        self,
        default_ttl: timedelta | None = None,
    ) -> None:
        """Initialize response cache."""
        self._cache: dict[str, tuple[Any, datetime]] = {}
        self._default_ttl = default_ttl or timedelta(seconds=30)
        self._lock = asyncio.Lock()

    def __len__(self) -> int:
        """Return the number of cached entries."""
        return len(self._cache)

    async def get(self, key: str, ttl: timedelta | None = None) -> Any | None:
        """Get cached response if still valid."""
        async with self._lock:
            if key not in self._cache:
                return None

            data, timestamp = self._cache[key]
            cache_ttl = ttl or self._default_ttl

            if _now_matching(timestamp) - timestamp > cache_ttl:
                del self._cache[key]
                return None

            return data

    async def set(self, key: str, value: Any) -> None:
        """Set cached response."""
        async with self._lock:
            self._cache[key] = (value, datetime.now(UTC))

    async def invalidate(self, key: str) -> None:
        """Remove a specific key from the cache."""
        async with self._lock:
            self._cache.pop(key, None)

    async def clear(self) -> None:
        """Clear all cached responses."""
        async with self._lock:
            self._cache.clear()

    async def cleanup_expired(self) -> None:
        """Remove expired entries from cache."""
        async with self._lock:
            expired_keys = [
                key
                for key, (_, timestamp) in self._cache.items()
                if _now_matching(timestamp) - timestamp > self._default_ttl
            ]
            for key in expired_keys:
                del self._cache[key]


class ActronAirNeoApiClient:
    """API client for the ActronAir Neo cloud service."""

    def __init__(
        self,
        auth: ActronAirNeoAuth,
        session: aiohttp.ClientSession,
    ) -> None:
        """Initialize the API client."""
        self.auth = auth
        self.session = session

        # Device identification
        self.actron_serial: str = ""
        self.actron_system_id: str = ""
        self._base_url: str = API_URL
        self._device_base_urls: dict[str, str] = {}
        self._device_links: dict[str, dict[str, str]] = {}
        self._account_email: str | None = None

        # API health tracking
        self.error_count: int = 0
        self.last_successful_request: datetime | None = None
        self.cached_status: dict[str, Any] | None = None
        # Circuit breaker: timestamp of the last half-open recovery probe.
        # Initialised to "now" so a freshly degraded client waits a full
        # cooldown before probing rather than probing immediately.
        self._last_health_probe_time: datetime = datetime.now(UTC)

        # Rate limiting and caching
        self.rate_limiter = RateLimiter(MAX_REQUESTS_PER_MINUTE)
        self.response_cache = ResponseCache(
            default_ttl=timedelta(seconds=DEFAULT_CACHE_TTL)
        )

        # Request deduplication
        self._pending_requests: dict[str, asyncio.Future[Any]] = {}

        # Fan mode management
        self._continuous_fan: bool = False
        self._last_fan_mode_change: datetime | None = None
        self._fan_mode_change_lock: asyncio.Lock = asyncio.Lock()
        self._min_fan_mode_interval: int = MIN_FAN_MODE_INTERVAL

        # Zone locks
        self._zone_locks: dict[int, asyncio.Lock] = {}

    @property
    def _circuit_open(self) -> bool:
        """Return True when too many recent errors have tripped the breaker."""
        _max_errors = 5
        _health_window_minutes = 15
        return bool(
            self.error_count > _max_errors
            and self.last_successful_request
            and _now_matching(self.last_successful_request)
            - self.last_successful_request
            < timedelta(minutes=_health_window_minutes)
        )

    def _is_health_probe_due(self) -> bool:
        """Return True when a half-open recovery probe is permitted."""
        return _now_matching(
            self._last_health_probe_time
        ) - self._last_health_probe_time >= timedelta(seconds=HEALTH_PROBE_COOLDOWN)

    def is_api_healthy(self) -> bool:
        """
        Check if the API is healthy based on recent error history.

        When the breaker is open we still permit a single half-open probe
        every ``HEALTH_PROBE_COOLDOWN`` seconds so the integration can
        recover automatically instead of serving stale data until the full
        health window elapses.
        """
        if not self._circuit_open:
            return True
        return self._is_health_probe_due()

    async def set_system(
        self,
        serial_number: str,
        system_id: str = "",
        base_url: str = "",
    ) -> None:
        """
        Set the system to use for API calls.

        The base URL is resolved in order of priority:
        1. Explicitly provided ``base_url``
        2. Platform detected during ``get_devices()``
        3. Default Nimbus (Neo) URL
        """
        self.actron_serial = serial_number
        self.actron_system_id = system_id
        if base_url:
            self._base_url = base_url
        elif serial_number in self._device_base_urls:
            self._base_url = self._device_base_urls[serial_number]
        # Sync OAuth endpoint base URL when switching between Neo and Que (PR #57)
        update_auth_url = getattr(self.auth, "update_base_url", None)
        if callable(update_auth_url):
            update_auth_url(self._base_url)

    async def initialize(self) -> None:
        """Initialize the API client by validating authentication."""
        await self.auth.ensure_valid_token()

        # Validate by fetching devices
        if self.auth.access_token and self.auth.refresh_token_value:
            await self.get_devices()

    # --- Core request method ---

    async def _make_request(
        self,
        method: str,
        url: str,
        *,
        auth_required: bool = True,
        **kwargs: Any,
    ) -> dict[str, Any] | str:
        """Make an API request with rate limiting and error handling."""
        async with self.rate_limiter:
            for attempt in range(MAX_RETRIES):
                try:
                    headers = dict(kwargs.pop("headers", {}))
                    if auth_required:
                        auth_headers = await self.auth.get_auth_headers()
                        headers.update(auth_headers)
                    kwargs["headers"] = headers

                    response_data = await self._execute_request(
                        method, url, attempt, **kwargs
                    )
                except ApiError as err:
                    self.error_count += 1
                    if (
                        err.status_code is not None
                        and err.status_code in RETRYABLE_STATUS_CODES
                        and attempt < MAX_RETRIES - 1
                    ):
                        _max_wait = 60
                        wait_time = min(5 * (2**attempt), _max_wait)
                        await asyncio.sleep(wait_time)
                        continue
                    raise
                except (
                    TimeoutError,
                    aiohttp.ClientError,
                ) as err:
                    self.error_count += 1
                    if attempt == MAX_RETRIES - 1:
                        _LOGGER.warning(
                            "Unable to connect to ActronAir servers "
                            "after multiple attempts."
                        )
                        msg = f"Request failed after {MAX_RETRIES} attempts: {err}"
                        raise ApiError(msg) from err
                    await asyncio.sleep(5 * (2**attempt))  # Exponential backoff
                else:
                    return response_data

        msg = f"Failed to make request after {MAX_RETRIES} attempts"
        raise ApiError(msg)

    async def _execute_request(
        self,
        method: str,
        url: str,
        attempt: int,
        **kwargs: Any,
    ) -> dict[str, Any] | str:
        """Execute a single HTTP request and handle the response."""
        async with self.session.request(
            method,
            url,
            timeout=aiohttp.ClientTimeout(total=API_TIMEOUT),
            **kwargs,
        ) as response:
            response_text = await response.text()

            response_json = self._try_parse_json(response_text)

            if response.status == 200:  # noqa: PLR2004
                self.error_count = 0
                self.last_successful_request = datetime.now(UTC)
                if response_json is not None:
                    return response_json
                return response_text

            return self._handle_error_status(response, response_text, attempt)

    def _try_parse_json(self, response_text: str) -> dict[str, Any] | None:
        """Attempt to parse response text as JSON, repairing firmware escapes."""
        try:
            result: dict[str, Any] = loads_repairing_escapes(response_text)
        except json.JSONDecodeError:
            return None
        else:
            return result

    def _handle_error_status(
        self,
        response: aiohttp.ClientResponse,
        response_text: str,
        attempt: int,
    ) -> Any:
        """Handle non-200 HTTP status codes."""
        status = response.status
        self.error_count += 1

        if status == 401:  # noqa: PLR2004
            msg = f"Unauthorized: {response_text}"
            raise AuthenticationError(msg)

        if status == 429:  # noqa: PLR2004
            retry_after = int(response.headers.get("Retry-After", "60"))
            _LOGGER.warning(
                "Rate limit exceeded, retry after %s seconds",
                retry_after,
            )
            msg = f"Rate limit exceeded, retry after {retry_after} seconds"
            raise RateLimitError(msg, retry_after=retry_after)

        if status == 503:  # noqa: PLR2004
            # Try structured JSON first (API returns {type, correlationId, …})
            parsed = self._try_parse_json(response_text)
            if isinstance(parsed, dict) and parsed.get("type") == "unavailable":
                msg = (
                    f"Device unavailable on this platform "
                    f"(serial={self.actron_serial}, "
                    f"base_url={self._base_url}): {response_text}"
                )
                raise DeviceOfflineError(
                    msg,
                    device_id=self.actron_serial or "unknown",
                )

            text_lower = response_text.lower()
            if "device" in text_lower or "offline" in text_lower:
                msg = f"Device appears to be offline: {response_text}"
                raise DeviceOfflineError(
                    msg,
                    device_id=self.actron_serial or "unknown",
                )
            msg = f"Service unavailable: {response_text}"
            raise ApiError(msg, status_code=status, retry_after=30)

        _http_client_error_min = 400
        _http_client_error_max = 500
        _http_server_error_min = 500
        _http_server_error_max = 600

        if _http_client_error_min <= status < _http_client_error_max:
            msg = f"Client error: {status}, {response_text}"
            raise ApiError(msg, status_code=status)

        if _http_server_error_min <= status < _http_server_error_max:
            return self._handle_server_error(status, response_text, attempt)

        msg = f"Unexpected status code: {status}, {response_text}"
        raise ApiError(msg, status_code=status)

    def _handle_server_error(
        self,
        status: int,
        response_text: str,
        attempt: int,
    ) -> Any:
        """Handle server errors with retry logic."""
        if attempt < MAX_RETRIES - 1:
            _max_wait = 60
            min(5 * (2**attempt), _max_wait)
            # Note: caller handles sleep/retry
        msg = f"Server error after {MAX_RETRIES} attempts: {status}, {response_text}"
        raise ApiError(msg, status_code=status)

    # --- Device and status methods ---

    @staticmethod
    def _extract_hal_links(system: dict[str, Any]) -> dict[str, str]:
        """Extract HAL _links mapping (rel -> href) from a system payload."""
        raw_links = system.get("_links")
        if not isinstance(raw_links, dict):
            return {}
        links: dict[str, str] = {}
        for rel, target in cast("dict[str, Any]", raw_links).items():
            if isinstance(target, dict):
                href = cast("dict[str, Any]", target).get("href")
                if isinstance(href, str) and href:
                    links[str(rel)] = href
        return links

    def _resolve_endpoint_url(
        self, serial: str, rel: str, default_path_with_query: str
    ) -> str:
        """Resolve a HAL link for ``serial`` or fall back to default path."""
        href = self._device_links.get(serial, {}).get(rel)
        if href:
            if href.startswith(("http://", "https://")):
                return href
            return f"{self._base_url}/{href.lstrip('/')}"
        return f"{self._base_url}{default_path_with_query}"

    async def get_devices(self) -> list[DeviceInfo]:
        """
        Fetch the list of devices from the API.

        Device discovery always queries the Nimbus (Neo) endpoint with
        ``includeNeo=true`` which returns devices from both platforms.
        Each device's ``type`` field is inspected: NX-Gen (Que-platform)
        systems are routed via the Que base URL for subsequent calls.
        """
        url = f"{API_URL}{ENDPOINT_AC_SYSTEMS}?includeNeo=true"
        response = await self._make_request("GET", url)
        devices: list[DeviceInfo] = []
        if (
            isinstance(response, dict)
            and "_embedded" in response
            and "ac-system" in response["_embedded"]
        ):
            for system in response["_embedded"]["ac-system"]:
                device_base_url = self._resolve_base_url(system)
                serial = str(system.get("serial", "Unknown"))
                hal_links = self._extract_hal_links(system)
                device = DeviceInfo(
                    serial=serial,
                    name=str(system.get("description", "Unknown Device")),
                    type=str(system.get("type", "Unknown")),
                    id=str(system.get("id", "Unknown")),
                    base_url=device_base_url,
                    links=hal_links,
                )
                devices.append(device)
                self._device_base_urls[serial] = device_base_url
                if hal_links:
                    self._device_links[serial] = hal_links
        return devices

    @staticmethod
    def _resolve_base_url(system: dict[str, Any]) -> str:
        """
        Determine the correct API base URL for a system.

        NX-Gen systems (Que hardware with Neo controllers) are served by
        the Que endpoint.  All other systems use the default Nimbus (Neo)
        endpoint.
        """
        raw_type = system.get("type", "")
        normalised = raw_type.lower().replace("-", "")
        if normalised == SYSTEM_TYPE_NXGEN:
            return API_URL_QUE
        return API_URL

    @staticmethod
    async def _await_pending_request(
        pending: asyncio.Future[Any], serial: str
    ) -> dict[str, Any] | None:
        """
        Wait for another caller's in-flight request for the same system.

        Return its response, or None when the caller should issue its own
        request because the shared request failed or its owner was cancelled.
        """
        try:
            # Shield so cancelling this waiter never cancels the shared
            # future that the owner and other waiters depend on.
            return cast("dict[str, Any]", await asyncio.shield(pending))
        except asyncio.CancelledError:
            # The owner cancels the shared future when it is itself cancelled;
            # only then issue our own request. Re-raise when this task is the
            # one being cancelled.
            task = asyncio.current_task()
            if not pending.cancelled() or (task is not None and task.cancelling()):
                raise
            _LOGGER.debug(
                "Pending request for %s was cancelled; issuing new request", serial
            )
        except (ActronAirNeoError, TimeoutError, aiohttp.ClientError) as err:
            _LOGGER.debug(
                "Pending request for %s failed (%s); issuing new request",
                serial,
                err,
            )
        return None

    @staticmethod
    def _release_pending_future(future: asyncio.Future[Any]) -> None:
        """Settle a published request future as its owner exits."""
        if not future.done():
            # The owner exited without a result or error (e.g. it was
            # cancelled): cancel the future so waiters are released instead
            # of hanging.
            future.cancel()
        elif not future.cancelled():
            # Safety net: retrieve any exception set via a path that bypassed
            # the except block, to prevent asyncio's "Future exception was
            # never retrieved" warning.
            with contextlib.suppress(Exception):
                future.exception()

    async def get_ac_status(
        self,
        serial: str,
        *,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        """Get the current status of the AC system."""
        # Check API health first
        if not self.is_api_healthy():
            _LOGGER.warning("API is not healthy, using cached status")
            return self.cached_status or {}

        # Try cache first if enabled
        cache_key = f"ac_status_{serial}"
        if use_cache:
            cached_response = await self.response_cache.get(cache_key)
            if cached_response is not None:
                return cast("dict[str, Any]", cached_response)

        # Check for pending request (deduplication)
        request_key = f"get_ac_status_{serial}"
        if (pending := self._pending_requests.get(request_key)) is not None:
            shared_response = await self._await_pending_request(pending, serial)
            if shared_response is not None:
                return shared_response

        # Create new request future
        future: asyncio.Future[Any] = asyncio.Future()
        self._pending_requests[request_key] = future

        try:
            # If the breaker is open we only reached here because a half-open
            # probe is due — record it so we don't hammer a degraded API.
            if self._circuit_open:
                self._last_health_probe_time = datetime.now(UTC)
                _LOGGER.debug("API degraded; sending half-open recovery probe")

            url = self._resolve_endpoint_url(
                serial, "ac-status", f"{ENDPOINT_AC_STATUS}?serial={serial}"
            )
            response = await self._make_request("GET", url)

            # Update both caches
            self.cached_status = response if isinstance(response, dict) else None
            if use_cache:
                await self.response_cache.set(cache_key, response)

            # Complete the future for other waiting requests
            if not future.done():
                future.set_result(response)

            return cast("dict[str, Any]", response)

        except Exception as err:
            if not future.done():
                future.set_exception(err)
            with contextlib.suppress(Exception):
                future.exception()
            raise
        finally:
            self._release_pending_future(future)
            self._pending_requests.pop(request_key, None)

    @property
    def platform(self) -> str:
        """Return the platform family ("neo" or "que") from the base URL."""
        return "que" if "que" in self._base_url.lower() else "neo"

    async def get_account_email(self) -> str:
        """
        Fetch the authenticated user's account email (used as MQTT username).

        Falls back to empty string if the endpoint is unavailable.
        """
        if self._account_email is not None:
            return self._account_email
        url = f"{self._base_url}{ENDPOINT_ACCOUNT}"
        try:
            response = await self._make_request("GET", url)
            if isinstance(response, dict):
                info = ActronAirUserInfo.model_validate(response)
                self._account_email = info.email
                return info.email
        except (ActronAirNeoError, ValidationError):
            _LOGGER.debug("Account email lookup failed; using empty MQTT username")
        self._account_email = ""
        return ""

    async def get_realtime_access_token(self) -> str:
        """Return a fresh OAuth access token for use as the MQTT password."""
        await self.auth.ensure_valid_token()
        token = self.auth.access_token
        if not token:
            msg = "No access token available for realtime push"
            raise AuthenticationError(msg)
        return token

    async def get_realtime_connection_details(
        self,
        serial: str,
    ) -> RealtimeConnectionDetails | None:
        """Fetch and parse broker connection details for realtime push."""
        url = self._resolve_endpoint_url(
            serial, "rtc-details", ENDPOINT_REALTIME_DETAILS
        )
        response = await self._make_request("GET", url)
        if not isinstance(response, dict):
            return None
        return RealtimeConnectionDetails.from_payload(response)

    async def send_command(
        self, serial: str, command: CommandData | dict[str, Any]
    ) -> dict[str, Any]:
        """Send a command to the AC system and invalidate cache."""
        url = self._resolve_endpoint_url(
            serial, "commands", f"{ENDPOINT_AC_COMMANDS}?serial={serial}"
        )

        # Convert CommandData to dict if needed
        cmd_dict = command.model_dump() if isinstance(command, CommandData) else command

        # The user's intent is to change device state, so any cached status is
        # stale the moment we attempt a command — invalidate it regardless of
        # whether the command ultimately succeeds or fails. See issue #112.
        try:
            for attempt in range(MAX_RETRIES):
                try:
                    response = await self._make_request("POST", url, json=cmd_dict)
                except ApiError as err:
                    if (
                        attempt < MAX_RETRIES - 1
                        and err.status_code in RETRYABLE_STATUS_CODES
                    ):
                        wait_time = 2**attempt
                        await asyncio.sleep(wait_time)
                    else:
                        raise
                except (
                    TimeoutError,
                    aiohttp.ClientError,
                    json.JSONDecodeError,
                ):
                    if attempt == MAX_RETRIES - 1:
                        raise
                    # Back off before retrying, matching the ApiError branch,
                    # so transient network errors don't hammer the API.
                    await asyncio.sleep(2**attempt)
                else:
                    return cast("dict[str, Any]", response)

            msg = f"Failed to send command after {MAX_RETRIES} attempts"
            raise ApiError(msg)
        finally:
            await self._invalidate_status_cache(serial)

    # --- Command creation ---

    def create_command(self, command_type: str, **params: Any) -> dict[str, Any]:
        """Create a command based on the command type and parameters."""
        settings = self._build_command_settings(command_type, params)
        settings["type"] = "set-settings"
        return {"command": settings}

    @staticmethod
    def _build_command_settings(  # noqa: PLR0911, PLR0912
        command_type: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Map a command type and its parameters to a settings payload.

        Return the path/value pairs for the command. ``create_command`` adds
        the ``type`` marker and wrapper.
        """
        match command_type:
            case "ON":
                return {"UserAirconSettings.isOn": True}
            case "OFF":
                return {"UserAirconSettings.isOn": False}
            case "CLIMATE_MODE":
                return {
                    "UserAirconSettings.isOn": True,
                    "UserAirconSettings.Mode": params["mode"],
                }
            case "FAN_MODE":
                return {"UserAirconSettings.FanMode": params["mode"]}
            case "SET_TEMP":
                suffix = "Cool" if params["is_cool"] else "Heat"
                return {
                    f"UserAirconSettings.TemperatureSetpoint_{suffix}_oC": (
                        params["temp"]
                    )
                }
            case "AWAY_MODE":
                return {"UserAirconSettings.AwayMode": params["state"]}
            case "SCHEDULE_EVENTS_ENABLED":
                positions = cast("tuple[object, ...] | None", params.get("positions"))
                if (
                    not isinstance(positions, tuple)
                    or not positions
                    or any(
                        type(position) is not int or position < 0
                        for position in positions
                    )
                ):
                    msg = "Schedule event positions must be non-negative integers"
                    raise ApiError(msg)
                return {
                    f"NV_Schedule.Events[{position}].Enabled": params["enabled"]
                    for position in cast("tuple[int, ...]", positions)
                }
            case "QUIET_MODE":
                return {"UserAirconSettings.QuietMode": params["state"]}
            case "SET_ZONE_TEMP":
                key = f"RemoteZoneInfo[{params['zone']}].{params['temp_key']}"
                return {key: params["temp"]}
            case "SET_ZONE_STATE":
                return {"UserAirconSettings.EnabledZones": params["zones"]}
            case "SET_ZONE_AIRFLOW":
                key = f"RemoteZoneInfo[{params['zone']}].AirflowSetpoint"
                return {key: params["airflow"]}
            case "TURBO_MODE":
                return {"UserAirconSettings.TurboMode.Enabled": params["state"]}
            case "AFTER_HOURS_ENABLED":
                return {"UserAirconSettings.AfterHours.Enabled": params["state"]}
            case "AFTER_HOURS_DURATION":
                return {"UserAirconSettings.AfterHours.Duration": params["duration"]}
            case _:
                msg = f"Unknown command type: {command_type}"
                raise ApiError(msg)

    # --- Zone operations ---

    async def get_zone_statuses(
        self,
        cached_status: dict[str, Any] | None = None,
    ) -> list[bool]:
        """Get the current status of all zones."""
        if cached_status is not None:
            status = cached_status
        else:
            status = await self.get_ac_status(self.actron_serial)

        try:
            enabled_zones = status["lastKnownState"]["UserAirconSettings"][
                "EnabledZones"
            ]
        except (KeyError, TypeError) as err:
            source = "cached_status" if cached_status is not None else "live API"
            msg = (
                f"Unable to read zone statuses for {self.actron_serial}: "
                f"malformed response ({source})"
            )
            raise ApiError(msg) from err

        if not isinstance(enabled_zones, list):
            msg = (
                f"Unable to read zone statuses for {self.actron_serial}: "
                f"EnabledZones is {type(enabled_zones).__name__}, expected list"
            )
            raise ApiError(msg)

        return cast("list[bool]", enabled_zones)

    async def set_zone_state(
        self,
        zone_index: int,
        *,
        enable: bool,
    ) -> None:
        """Set the state of a specific zone."""
        if not (0 <= zone_index < 8):  # noqa: PLR2004
            msg = f"zone_index must be between 0 and 7, got {zone_index}"
            raise ValueError(msg)
        current_zone_status = await self.get_zone_statuses()
        modified_statuses = current_zone_status.copy()
        modified_statuses[zone_index] = enable
        command = self.create_command("SET_ZONE_STATE", zones=modified_statuses)
        await self.send_command(self.actron_serial, command)

    def get_zone_capabilities(
        self, zone_data: dict[str, str | int | bool | float]
    ) -> ZoneCapabilities:
        """Extract zone capabilities from zone data."""
        nv_vav = bool(zone_data.get("NV_VAV", False))
        nv_itc = bool(zone_data.get("NV_ITC", False))
        return ZoneCapabilities(
            can_operate=bool(zone_data.get("CanOperate", False)),
            exists=bool(zone_data.get("NV_Exists", False)),
            has_temp_control=bool(nv_vav and nv_itc),
            has_separate_targets=bool(
                zone_data.get("TemperatureSetpoint_Cool_oC") is not None
                and zone_data.get("TemperatureSetpoint_Heat_oC") is not None
            ),
            target_temp_cool=cast(
                "float | None", zone_data.get("TemperatureSetpoint_Cool_oC")
            ),
            target_temp_heat=cast(
                "float | None", zone_data.get("TemperatureSetpoint_Heat_oC")
            ),
            nv_vav=nv_vav,
            nv_itc=nv_itc,
            nv_itd=bool(zone_data.get("NV_ITD", False)),
            nv_ihd=bool(zone_data.get("NV_IHD", False)),
            nv_iac=bool(zone_data.get("NV_IAC", False)),
        )

    async def set_zone_temperature(
        self,
        zone_index: int,
        temperature: float | None = None,
        target_cool: float | None = None,
        target_heat: float | None = None,
    ) -> None:
        """Set zone temperature with validation."""
        _max_zones = 8
        _min_temp = 10
        _max_temp = 30

        # Validate zone index
        if not 0 <= zone_index < _max_zones:
            msg = f"Zone index {zone_index} out of bounds"
            raise IndexError(msg)

        # Validate temperature values
        for temp in [
            t for t in [temperature, target_cool, target_heat] if t is not None
        ]:
            if not _min_temp <= temp <= _max_temp:
                msg = f"Temperature {temp} outside valid range {_min_temp}-{_max_temp}"
                raise ValueError(msg)

        # Use a lock to prevent concurrent zone updates
        async with self._zone_locks.setdefault(zone_index, asyncio.Lock()):
            if temperature is not None:
                command = self.create_command(
                    "SET_ZONE_TEMP",
                    zone=zone_index,
                    temp=temperature,
                    temp_key="TemperatureSetpoint_oC",
                )
            elif target_cool is not None and target_heat is not None:
                await self.send_command(
                    self.actron_serial,
                    self.create_command(
                        "SET_ZONE_TEMP",
                        zone=zone_index,
                        temp=target_cool,
                        temp_key="TemperatureSetpoint_Cool_oC",
                    ),
                )
                command = self.create_command(
                    "SET_ZONE_TEMP",
                    zone=zone_index,
                    temp=target_heat,
                    temp_key="TemperatureSetpoint_Heat_oC",
                )
            else:
                msg = (
                    "Must provide either temperature or both "
                    "target_cool and target_heat"
                )
                raise ValueError(msg)

            await self.send_command(self.actron_serial, command)

    async def set_zone_airflow(self, zone_index: int, airflow_percentage: int) -> None:
        """Set zone airflow percentage (YourZone control)."""
        _max_zones = 8
        _max_airflow = 100
        _airflow_step = 5

        if not 0 <= zone_index < _max_zones:
            msg = f"Zone index {zone_index} out of bounds"
            raise IndexError(msg)

        if not 0 <= airflow_percentage <= _max_airflow:
            msg = (
                f"Airflow percentage {airflow_percentage} "
                f"out of range (0-{_max_airflow})"
            )
            raise ValueError(msg)

        if airflow_percentage % _airflow_step != 0:
            msg = (
                f"Airflow percentage must be in "
                f"{_airflow_step}% increments, "
                f"got {airflow_percentage}"
            )
            raise ValueError(msg)

        async with self._zone_locks.setdefault(zone_index, asyncio.Lock()):
            command = self.create_command(
                "SET_ZONE_AIRFLOW",
                zone=zone_index,
                airflow=airflow_percentage,
            )
            await self.send_command(self.actron_serial, command)

    # --- HVAC control methods ---

    async def set_climate_mode(self, mode: HvacModeType) -> None:
        """Set the climate mode."""
        command = self.create_command("CLIMATE_MODE", mode=mode)
        await self.send_command(self.actron_serial, command)

    async def set_fan_mode(
        self,
        mode: FanModeType,
        *,
        continuous: bool | None = None,
    ) -> None:
        """Set fan mode with validation and retry logic."""
        if continuous is None:
            continuous = self._continuous_fan

        async with self._fan_mode_change_lock:
            if self._last_fan_mode_change:
                elapsed = (
                    _now_matching(self._last_fan_mode_change)
                    - self._last_fan_mode_change
                ).total_seconds()
                if elapsed < self._min_fan_mode_interval:
                    wait_time = self._min_fan_mode_interval - elapsed
                    await asyncio.sleep(wait_time)

            validated_mode = self.validate_fan_mode(mode, continuous=continuous)

            for attempt in range(MAX_RETRIES):
                try:
                    command = self.create_command("FAN_MODE", mode=validated_mode)
                    await self.send_command(self.actron_serial, command)
                except ApiError as api_err:
                    if (
                        api_err.status_code in RETRYABLE_STATUS_CODES
                        and attempt < MAX_RETRIES - 1
                    ):
                        _max_backoff = 30
                        wait_time = min(2**attempt, _max_backoff)
                        await asyncio.sleep(wait_time)
                        continue
                    raise
                else:
                    self._last_fan_mode_change = datetime.now(UTC)
                    self._continuous_fan = continuous
                    return

    def validate_fan_mode(
        self,
        mode: str,
        *,
        continuous: bool = False,
    ) -> str:
        """Validate and format fan mode."""
        try:
            if not mode:
                return "LOW+CONT" if continuous else "LOW"

            base_mode = mode.strip().upper()
            base_mode = base_mode.split("-")[0] if "-" in base_mode else base_mode
            base_mode = base_mode.split("+")[0] if "+" in base_mode else base_mode

            valid_modes = {"LOW", "MED", "HIGH", "AUTO"}
            if base_mode not in valid_modes:
                base_mode = "LOW"
        except (ValueError, KeyError, TypeError):
            return "LOW+CONT" if continuous else "LOW"
        else:
            return f"{base_mode}+CONT" if continuous else base_mode

    async def set_temperature(
        self,
        temperature: float,
        *,
        is_cooling: bool,
    ) -> None:
        """Set the temperature."""
        command = self.create_command("SET_TEMP", temp=temperature, is_cool=is_cooling)
        await self.send_command(self.actron_serial, command)

    async def set_away_mode(self, *, state: bool) -> None:
        """Set away mode."""
        command = self.create_command("AWAY_MODE", state=state)
        await self.send_command(self.actron_serial, command)

    async def set_schedule_events_enabled(
        self, positions: tuple[int, ...], *, enabled: bool
    ) -> None:
        """Set selected controller events in one indexed settings command."""
        command = self.create_command(
            "SCHEDULE_EVENTS_ENABLED", positions=positions, enabled=enabled
        )
        await self.send_command(self.actron_serial, command)

    async def set_schedule_event_enabled(self, position: int, *, enabled: bool) -> None:
        """Set one controller schedule event by its list position."""
        await self.set_schedule_events_enabled((position,), enabled=enabled)

    async def set_quiet_mode(self, *, state: bool) -> None:
        """Set quiet mode."""
        command = self.create_command("QUIET_MODE", state=state)
        await self.send_command(self.actron_serial, command)

    async def set_turbo_mode(self, *, state: bool) -> None:
        """Set turbo mode."""
        command = self.create_command("TURBO_MODE", state=state)
        await self.send_command(self.actron_serial, command)

    async def set_after_hours(self, *, enabled: bool) -> None:
        """Set after hours mode enabled/disabled."""
        command = self.create_command("AFTER_HOURS_ENABLED", state=enabled)
        await self.send_command(self.actron_serial, command)

    async def set_after_hours_duration(self, duration: int) -> None:
        """Set after hours duration in minutes."""
        command = self.create_command("AFTER_HOURS_DURATION", duration=duration)
        await self.send_command(self.actron_serial, command)

    # --- Cache management ---

    async def invalidate_status_cache(self, serial: str) -> None:
        """Invalidate cached status data after commands."""
        cache_key = f"ac_status_{serial}"
        await self.response_cache.invalidate(cache_key)
        self.cached_status = None

    # Backward-compatible alias for internal/test usage
    _invalidate_status_cache = invalidate_status_cache

    async def clear_all_caches(self) -> None:
        """Clear all cached data."""
        await self.response_cache.clear()
        self.cached_status = None

    async def cleanup_expired_cache(self) -> None:
        """Clean up expired cache entries."""
        await self.response_cache.cleanup_expired()
