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
import typing

from tenacity import _utils, retry_base
from tenacity._utils import override
from tenacity.retry import (
    retry_always,
    retry_if_exception_cause_type,
    retry_if_exception_message,
    retry_if_exception_type,
    retry_if_not_exception_message,
    retry_if_not_exception_type,
    retry_if_not_result,
    retry_never,
    retry_unless_exception_type,
)

if typing.TYPE_CHECKING:
    from tenacity import RetryCallState


__all__ = [
    "RetryBaseT",
    "async_retry_base",
    "retry_all",
    "retry_always",
    "retry_any",
    "retry_base",
    "retry_if_exception",
    "retry_if_exception_cause_type",
    "retry_if_exception_message",
    "retry_if_exception_type",
    "retry_if_not_exception_message",
    "retry_if_not_exception_type",
    "retry_if_not_result",
    "retry_if_result",
    "retry_never",
    "retry_unless_exception_type",
]


class async_retry_base(retry_base):
    """Abstract base class for async retry strategies.

    Combination (``&``/``|``) is inherited from
    :class:`tenacity.retry.retry_base`: the same rules decide there, in one
    place, whether the combined strategy is synchronous or asynchronous.
    """

    @abc.abstractmethod
    @override
    async def __call__(self, retry_state: "RetryCallState") -> bool:
        pass


RetryBaseT: typing.TypeAlias = (
    retry_base
    | typing.Callable[["RetryCallState"], bool]
    | typing.Callable[["RetryCallState"], typing.Awaitable[bool]]
)


class retry_if_exception(async_retry_base):
    """Retry strategy that retries if an exception verifies a predicate."""

    def __init__(
        self,
        predicate: typing.Callable[[BaseException], bool | typing.Awaitable[bool]],
    ) -> None:
        self.predicate: typing.Callable[[BaseException], typing.Awaitable[bool]] = (
            _utils.wrap_to_async_func(predicate)
        )

    @override
    async def __call__(self, retry_state: "RetryCallState") -> bool:
        if retry_state.outcome is None:
            raise RuntimeError("__call__() called before outcome was set")

        if retry_state.outcome.failed:
            exception = retry_state.outcome.exception()
            if exception is None:
                raise RuntimeError("outcome failed but the exception is None")
            return await self.predicate(exception)
        return False


class retry_if_result(async_retry_base):
    """Retries if the result verifies a predicate."""

    def __init__(
        self,
        predicate: typing.Callable[[typing.Any], bool | typing.Awaitable[bool]],
    ) -> None:
        self.predicate: typing.Callable[[typing.Any], typing.Awaitable[bool]] = (
            _utils.wrap_to_async_func(predicate)
        )

    @override
    async def __call__(self, retry_state: "RetryCallState") -> bool:
        if retry_state.outcome is None:
            raise RuntimeError("__call__() called before outcome was set")

        if not retry_state.outcome.failed:
            return await self.predicate(retry_state.outcome.result())
        return False


class retry_any(async_retry_base):
    """Retries if any of the retries condition is valid."""

    def __init__(self, *retries: RetryBaseT) -> None:
        self.retries = retries

    @override
    async def __call__(self, retry_state: "RetryCallState") -> bool:
        result = False
        for r in self.retries:
            result = result or await _utils.wrap_to_async_func(r)(retry_state)
            if result:
                break
        return result


class retry_all(async_retry_base):
    """Retries if all the retries condition are valid."""

    def __init__(self, *retries: RetryBaseT) -> None:
        self.retries = retries

    @override
    async def __call__(self, retry_state: "RetryCallState") -> bool:
        result = True
        for r in self.retries:
            result = result and await _utils.wrap_to_async_func(r)(retry_state)
            if not result:
                break
        return result
