# Copyright 2016–2021 Julien Danjou
# Copyright 2016 Joshua Harlow
# Copyright 2013-2014 Ray Holder
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import abc
import inspect
import re
import typing

from tenacity import _utils
from tenacity._utils import override

if typing.TYPE_CHECKING:
    from tenacity import RetryCallState
    from tenacity.asyncio import retry as async_retry


def _unnest(operand: typing.Any, *combinators: type) -> tuple[typing.Any, ...]:
    """Return the members of a combinator, or the operand itself."""
    if isinstance(operand, combinators):
        # isinstance() narrows the Any operand to object; cast it back.
        return tuple(typing.cast("typing.Any", operand).retries)
    return (operand,)


def _combine_all(
    left: "AnyRetryBaseT", right: "AnyRetryBaseT"
) -> "retry_all | async_retry.retry_all":
    """Combine two retry conditions with ``&``.

    This is the single place deciding how conditions combine: if either
    operand needs awaiting (an async retry strategy or a coroutine
    callable), the combination is the async combinator so the verdict is
    computed the same way no matter which side the async condition sits on.
    """
    if _utils.is_coroutine_callable(left) or _utils.is_coroutine_callable(right):
        from tenacity.asyncio.retry import retry_all as async_retry_all

        return async_retry_all(
            *_unnest(left, retry_all, async_retry_all),
            *_unnest(right, retry_all, async_retry_all),
        )
    return retry_all(*_unnest(left, retry_all), *_unnest(right, retry_all))


def _combine_any(
    left: "AnyRetryBaseT", right: "AnyRetryBaseT"
) -> "retry_any | async_retry.retry_any":
    """Combine two retry conditions with ``|``; see :func:`_combine_all`."""
    if _utils.is_coroutine_callable(left) or _utils.is_coroutine_callable(right):
        from tenacity.asyncio.retry import retry_any as async_retry_any

        return async_retry_any(
            *_unnest(left, retry_any, async_retry_any),
            *_unnest(right, retry_any, async_retry_any),
        )
    return retry_any(*_unnest(left, retry_any), *_unnest(right, retry_any))


class retry_base(abc.ABC):
    """Abstract base class for retry strategies."""

    @abc.abstractmethod
    def __call__(self, retry_state: "RetryCallState") -> bool | typing.Awaitable[bool]:
        """Return whether to retry.

        May return an awaitable when the condition involves async
        predicates; asynchronous retry runners await it, the synchronous
        runner rejects it.
        """

    def __and__(self, other: "AnyRetryBaseT") -> "retry_all | async_retry.retry_all":
        return _combine_all(self, other)

    def __rand__(self, other: "AnyRetryBaseT") -> "retry_all | async_retry.retry_all":
        return _combine_all(other, self)

    def __or__(self, other: "AnyRetryBaseT") -> "retry_any | async_retry.retry_any":
        return _combine_any(self, other)

    def __ror__(self, other: "AnyRetryBaseT") -> "retry_any | async_retry.retry_any":
        return _combine_any(other, self)


RetryBaseT = retry_base | typing.Callable[["RetryCallState"], bool]
# Anything that can play the role of a retry condition, including
# conditions that can only be evaluated asynchronously.
AnyRetryBaseT = RetryBaseT | typing.Callable[["RetryCallState"], typing.Awaitable[bool]]


class _retry_never(retry_base):
    """Retry strategy that never rejects any result."""

    @override
    def __call__(self, retry_state: "RetryCallState") -> bool:
        return False


retry_never = _retry_never()


async def _negate(awaitable: typing.Awaitable[bool]) -> bool:
    return not await awaitable


class _retry_always(retry_base):
    """Retry strategy that always rejects any result."""

    @override
    def __call__(self, retry_state: "RetryCallState") -> bool:
        return True


retry_always = _retry_always()


class retry_if_exception(retry_base):
    """Retry strategy that retries if an exception verifies a predicate."""

    def __init__(
        self,
        predicate: typing.Callable[[BaseException], bool | typing.Awaitable[bool]],
    ) -> None:
        self.predicate = predicate

    @override
    def __call__(self, retry_state: "RetryCallState") -> bool | typing.Awaitable[bool]:
        if retry_state.outcome is None:
            raise RuntimeError("__call__() called before outcome was set")

        if retry_state.outcome.failed:
            exception = retry_state.outcome.exception()
            if exception is None:
                raise RuntimeError("outcome failed but the exception is None")
            return self.predicate(exception)
        return False


class retry_if_exception_type(retry_if_exception):
    """Retries if an exception has been raised of one or more types."""

    def __init__(
        self,
        exception_types: type[BaseException]
        | tuple[type[BaseException], ...] = Exception,
    ) -> None:
        self.exception_types = exception_types
        super().__init__(self._check)

    def _check(self, e: BaseException) -> bool:
        return isinstance(e, self.exception_types)


class retry_if_not_exception_type(retry_if_exception):
    """Retries except an exception has been raised of one or more types."""

    def __init__(
        self,
        exception_types: type[BaseException]
        | tuple[type[BaseException], ...] = Exception,
    ) -> None:
        self.exception_types = exception_types
        super().__init__(self._check)

    def _check(self, e: BaseException) -> bool:
        return not isinstance(e, self.exception_types)


class retry_unless_exception_type(retry_if_exception):
    """Retries until an exception is raised of one or more types."""

    def __init__(
        self,
        exception_types: type[BaseException]
        | tuple[type[BaseException], ...] = Exception,
    ) -> None:
        self.exception_types = exception_types
        super().__init__(self._check)

    def _check(self, e: BaseException) -> bool:
        return not isinstance(e, self.exception_types)

    @override
    def __call__(self, retry_state: "RetryCallState") -> bool | typing.Awaitable[bool]:
        if retry_state.outcome is None:
            raise RuntimeError("__call__() called before outcome was set")

        # always retry if no exception was raised
        if not retry_state.outcome.failed:
            return True

        exception = retry_state.outcome.exception()
        if exception is None:
            raise RuntimeError("outcome failed but the exception is None")
        return self.predicate(exception)


class retry_if_exception_cause_type(retry_base):
    """Retries if any of the causes of the raised exception is of one or more types.

    The check on the type of the cause of the exception is done recursively (until finding
    an exception in the chain that has no ``__cause__``, or a cycle is detected).
    """

    def __init__(
        self,
        exception_types: type[BaseException]
        | tuple[type[BaseException], ...] = Exception,
    ) -> None:
        self.exception_cause_types = exception_types

    @override
    def __call__(self, retry_state: "RetryCallState") -> bool:
        if retry_state.outcome is None:
            raise RuntimeError("__call__ called before outcome was set")

        if retry_state.outcome.failed:
            exc = retry_state.outcome.exception()
            # Guard against cyclic __cause__ chains (e.g. ``raise e from e``),
            # which would otherwise spin forever inside the predicate and
            # prevent stop conditions from ever running (see #658).
            seen: set[int] = set()
            while exc is not None and id(exc) not in seen:
                seen.add(id(exc))
                if isinstance(exc.__cause__, self.exception_cause_types):
                    return True
                exc = exc.__cause__

        return False


class retry_if_result(retry_base):
    """Retries if the result verifies a predicate."""

    def __init__(
        self,
        predicate: typing.Callable[[typing.Any], bool | typing.Awaitable[bool]],
    ) -> None:
        self.predicate = predicate

    @override
    def __call__(self, retry_state: "RetryCallState") -> bool | typing.Awaitable[bool]:
        if retry_state.outcome is None:
            raise RuntimeError("__call__() called before outcome was set")

        if not retry_state.outcome.failed:
            return self.predicate(retry_state.outcome.result())
        return False


class retry_if_not_result(retry_base):
    """Retries if the result refutes a predicate."""

    def __init__(
        self,
        predicate: typing.Callable[[typing.Any], bool | typing.Awaitable[bool]],
    ) -> None:
        self.predicate = predicate

    @override
    def __call__(self, retry_state: "RetryCallState") -> bool | typing.Awaitable[bool]:
        if retry_state.outcome is None:
            raise RuntimeError("__call__() called before outcome was set")

        if not retry_state.outcome.failed:
            result = self.predicate(retry_state.outcome.result())
            if inspect.isawaitable(result):
                return _negate(result)
            return not result
        return False


class retry_if_exception_message(retry_if_exception):
    """Retries if an exception message equals or matches."""

    def __init__(
        self,
        message: str | None = None,
        match: str | re.Pattern[str] | None = None,
    ) -> None:
        if message is not None and match is not None:
            raise TypeError(
                f"{self.__class__.__name__}() takes either 'message' or 'match', not both"
            )

        if message is None and match is None:
            raise TypeError(
                f"{self.__class__.__name__}() missing 1 required argument 'message' or 'match'"
            )

        self.message = message
        self.match: re.Pattern[str] | None = (
            re.compile(match) if match is not None else None
        )
        super().__init__(self._check)

    def _check(self, exception: BaseException) -> bool:
        if self.message is not None:
            return self.message == str(exception)
        assert self.match is not None
        return bool(self.match.match(str(exception)))


class retry_if_not_exception_message(retry_if_exception_message):
    """Retries until an exception message equals or matches."""

    @override
    def _check(self, exception: BaseException) -> bool:
        return not super()._check(exception)

    @override
    def __call__(self, retry_state: "RetryCallState") -> bool | typing.Awaitable[bool]:
        if retry_state.outcome is None:
            raise RuntimeError("__call__() called before outcome was set")

        if not retry_state.outcome.failed:
            return True

        exception = retry_state.outcome.exception()
        if exception is None:
            raise RuntimeError("outcome failed but the exception is None")
        return self.predicate(exception)


class retry_any(retry_base):
    """Retries if any of the retries condition is valid."""

    def __init__(self, *retries: "AnyRetryBaseT") -> None:
        self.retries = retries

    @override
    def __call__(self, retry_state: "RetryCallState") -> bool | typing.Awaitable[bool]:
        remaining = iter(self.retries)
        for retry in remaining:
            result = retry(retry_state)
            if inspect.isawaitable(result):
                return self._resolve_async(result, remaining, retry_state)
            if result:
                return True
        return False

    async def _resolve_async(
        self,
        first: typing.Awaitable[bool],
        remaining: typing.Iterator["AnyRetryBaseT"],
        retry_state: "RetryCallState",
    ) -> bool:
        if await first:
            return True
        for retry in remaining:
            result = retry(retry_state)
            if inspect.isawaitable(result):
                result = await result
            if result:
                return True
        return False


class retry_all(retry_base):
    """Retries if all the retries condition are valid."""

    def __init__(self, *retries: "AnyRetryBaseT") -> None:
        self.retries = retries

    @override
    def __call__(self, retry_state: "RetryCallState") -> bool | typing.Awaitable[bool]:
        remaining = iter(self.retries)
        for retry in remaining:
            result = retry(retry_state)
            if inspect.isawaitable(result):
                return self._resolve_async(result, remaining, retry_state)
            if not result:
                return False
        return True

    async def _resolve_async(
        self,
        first: typing.Awaitable[bool],
        remaining: typing.Iterator["AnyRetryBaseT"],
        retry_state: "RetryCallState",
    ) -> bool:
        if not await first:
            return False
        for retry in remaining:
            result = retry(retry_state)
            if inspect.isawaitable(result):
                result = await result
            if not result:
                return False
        return True
