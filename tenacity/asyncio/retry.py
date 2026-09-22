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
import typing

from tenacity.retry import (
    RetryBaseT as SyncRetryBaseT,
)
from tenacity.retry import (
    _retry_always as sync_retry_always,
)
from tenacity.retry import (
    _retry_never as sync_retry_never,
)
from tenacity.retry import (
    retry_all as sync_retry_all,
)
from tenacity.retry import (
    retry_any as sync_retry_any,
)
from tenacity.retry import (
    retry_base as sync_retry_base,
)
from tenacity.retry import (
    retry_if_exception as sync_retry_if_exception,
)
from tenacity.retry import (
    retry_if_exception_cause_type as sync_retry_if_exception_cause_type,
)
from tenacity.retry import (
    retry_if_exception_message as sync_retry_if_exception_message,
)
from tenacity.retry import (
    retry_if_exception_type as sync_retry_if_exception_type,
)
from tenacity.retry import (
    retry_if_not_exception_message as sync_retry_if_not_exception_message,
)
from tenacity.retry import (
    retry_if_not_exception_type as sync_retry_if_not_exception_type,
)
from tenacity.retry import (
    retry_if_not_result as sync_retry_if_not_result,
)
from tenacity.retry import (
    retry_if_result as sync_retry_if_result,
)
from tenacity.retry import (
    retry_unless_exception_type as sync_retry_unless_exception_type,
)

if typing.TYPE_CHECKING:
    from tenacity import RetryCallState


class async_retry_base(sync_retry_base):
    """Abstract base class for async retry strategies."""

    _is_async = True


retry_base = async_retry_base

RetryBaseT = (
    async_retry_base | typing.Callable[["RetryCallState"], typing.Awaitable[bool]]
)


class retry_if_exception(async_retry_base, sync_retry_if_exception):
    pass


class retry_if_exception_type(async_retry_base, sync_retry_if_exception_type):
    pass


class retry_if_not_exception_type(async_retry_base, sync_retry_if_not_exception_type):
    pass


class retry_unless_exception_type(async_retry_base, sync_retry_unless_exception_type):
    pass


class retry_if_exception_cause_type(
    async_retry_base, sync_retry_if_exception_cause_type
):
    pass


class retry_if_result(async_retry_base, sync_retry_if_result):
    pass


class retry_if_not_result(async_retry_base, sync_retry_if_not_result):
    pass


class retry_if_exception_message(async_retry_base, sync_retry_if_exception_message):
    pass


class retry_if_not_exception_message(
    async_retry_base, sync_retry_if_not_exception_message
):
    pass


class _retry_never(async_retry_base, sync_retry_never):
    pass


retry_never = _retry_never()


class _retry_always(async_retry_base, sync_retry_always):
    pass


retry_always = _retry_always()


class retry_any(async_retry_base, sync_retry_any):
    def __init__(self, *retries: SyncRetryBaseT | async_retry_base) -> None:
        super().__init__(*retries)


class retry_all(async_retry_base, sync_retry_all):
    def __init__(self, *retries: SyncRetryBaseT | async_retry_base) -> None:
        super().__init__(*retries)


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
