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

from tenacity._utils import is_coroutine_callable, override

if typing.TYPE_CHECKING:
    from tenacity import RetryCallState


PredicateResultT = bool | typing.Awaitable[bool]
RetryResultT = bool | typing.Coroutine[typing.Any, typing.Any, bool]


class retry_base(abc.ABC):
    """Abstract base class for retry strategies."""

    _is_async = False

    @abc.abstractmethod
    def __call__(self, retry_state: "RetryCallState") -> RetryResultT:
        pass

    def __and__(self, other: "RetryBaseT") -> "retry_all":
        return _combine_retries(retry_all, self, other)

    def __rand__(self, other: "RetryBaseT") -> "retry_all":
        return _combine_retries(retry_all, other, self)

    def __or__(self, other: "RetryBaseT") -> "retry_any":
        return _combine_retries(retry_any, self, other)

    def __ror__(self, other: "RetryBaseT") -> "retry_any":
        return _combine_retries(retry_any, other, self)


RetryBaseT = retry_base | typing.Callable[["RetryCallState"], PredicateResultT]
RetryCombinerT = typing.TypeVar("RetryCombinerT", "retry_any", "retry_all")


def _predicate_result(result: PredicateResultT) -> RetryResultT:
    if inspect.isawaitable(result):
        return typing.cast("typing.Coroutine[typing.Any, typing.Any, bool]", result)
    return bool(result)


async def _negate_predicate_result(result: typing.Awaitable[typing.Any]) -> bool:
    return not bool(await result)


def _is_async_retry(retry: RetryBaseT) -> bool:
    if is_coroutine_callable(retry):
        return True
    if not isinstance(retry, retry_base):
        return False
    if getattr(retry, "_is_async", False):
        return True
    predicate = getattr(retry, "predicate", None)
    if callable(predicate) and is_coroutine_callable(predicate):
        return True
    retries = getattr(retry, "retries", None)
    return isinstance(retries, tuple) and any(
        _is_async_retry(member) for member in retries
    )


def _combine_retries(
    combiner: type[RetryCombinerT], *retries: RetryBaseT
) -> RetryCombinerT:
    members: list[RetryBaseT] = []
    for retry in retries:
        if isinstance(retry, combiner):
            members.extend(retry.retries)
        else:
            members.append(retry)

    if any(_is_async_retry(retry) for retry in members):
        from tenacity.asyncio import retry as async_retry

        async_combiner = getattr(async_retry, combiner.__name__)
        return typing.cast("RetryCombinerT", async_combiner(*members))
    return combiner(*members)


class _retry_never(retry_base):
    """Retry strategy that never rejects any result."""

    @override
    def __call__(self, retry_state: "RetryCallState") -> RetryResultT:
        return False


retry_never = _retry_never()


class _retry_always(retry_base):
    """Retry strategy that always rejects any result."""

    @override
    def __call__(self, retry_state: "RetryCallState") -> RetryResultT:
        return True


retry_always = _retry_always()


class retry_if_exception(retry_base):
    """Retry strategy that retries if an exception verifies a predicate."""

    def __init__(
        self, predicate: typing.Callable[[BaseException], PredicateResultT]
    ) -> None:
        self.predicate = predicate

    @override
    def __call__(self, retry_state: "RetryCallState") -> RetryResultT:
        if retry_state.outcome is None:
            raise RuntimeError("__call__() called before outcome was set")

        if retry_state.outcome.failed:
            exception = retry_state.outcome.exception()
            if exception is None:
                raise RuntimeError("outcome failed but the exception is None")
            return _predicate_result(self.predicate(exception))
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
    def __call__(self, retry_state: "RetryCallState") -> RetryResultT:
        if retry_state.outcome is None:
            raise RuntimeError("__call__() called before outcome was set")

        # always retry if no exception was raised
        if not retry_state.outcome.failed:
            return True

        exception = retry_state.outcome.exception()
        if exception is None:
            raise RuntimeError("outcome failed but the exception is None")
        return _predicate_result(self.predicate(exception))


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
    def __call__(self, retry_state: "RetryCallState") -> RetryResultT:
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
        self, predicate: typing.Callable[[typing.Any], PredicateResultT]
    ) -> None:
        self.predicate = predicate

    @override
    def __call__(self, retry_state: "RetryCallState") -> RetryResultT:
        if retry_state.outcome is None:
            raise RuntimeError("__call__() called before outcome was set")

        if not retry_state.outcome.failed:
            return _predicate_result(self.predicate(retry_state.outcome.result()))
        return False


class retry_if_not_result(retry_base):
    """Retries if the result refutes a predicate."""

    def __init__(
        self, predicate: typing.Callable[[typing.Any], PredicateResultT]
    ) -> None:
        self.predicate = predicate

    @override
    def __call__(self, retry_state: "RetryCallState") -> RetryResultT:
        if retry_state.outcome is None:
            raise RuntimeError("__call__() called before outcome was set")

        if not retry_state.outcome.failed:
            result = self.predicate(retry_state.outcome.result())
            if inspect.isawaitable(result):
                return _negate_predicate_result(result)
            return not bool(result)
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
    def __call__(self, retry_state: "RetryCallState") -> RetryResultT:
        if retry_state.outcome is None:
            raise RuntimeError("__call__() called before outcome was set")

        if not retry_state.outcome.failed:
            return True

        exception = retry_state.outcome.exception()
        if exception is None:
            raise RuntimeError("outcome failed but the exception is None")
        return bool(self.predicate(exception))


class retry_any(retry_base):
    """Retries if any of the retries condition is valid."""

    def __init__(self, *retries: "RetryBaseT") -> None:
        self.retries = retries

    @override
    def __call__(self, retry_state: "RetryCallState") -> RetryResultT:
        if any(_is_async_retry(retry) for retry in self.retries):
            return _evaluate_any(retry_state, self.retries)
        return any(r(retry_state) for r in self.retries)


class retry_all(retry_base):
    """Retries if all the retries condition are valid."""

    def __init__(self, *retries: "RetryBaseT") -> None:
        self.retries = retries

    @override
    def __call__(self, retry_state: "RetryCallState") -> RetryResultT:
        if any(_is_async_retry(retry) for retry in self.retries):
            return _evaluate_all(retry_state, self.retries)
        return all(r(retry_state) for r in self.retries)


async def _evaluate_any(
    retry_state: "RetryCallState", retries: tuple[RetryBaseT, ...]
) -> bool:
    result = False
    for retry in retries:
        value = retry(retry_state)
        if inspect.isawaitable(value):
            value = await value
        result = bool(value)
        if result:
            break
    return result


async def _evaluate_all(
    retry_state: "RetryCallState", retries: tuple[RetryBaseT, ...]
) -> bool:
    result = True
    for retry in retries:
        value = retry(retry_state)
        if inspect.isawaitable(value):
            value = await value
        result = bool(value)
        if not result:
            break
    return result
