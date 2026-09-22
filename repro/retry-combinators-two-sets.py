import asyncio
import inspect
import warnings

import tenacity
from tenacity import retry_if_exception_type, retry_if_result
from tenacity.asyncio import retry_any, retry_if_result as a_retry_if_result

print("=== 1) 异步侧有哪些断言器（tenacity.asyncio.retry 的全部公开名）")
import tenacity.asyncio.retry as ar

print("asyncio.retry ->", sorted(n for n in dir(ar) if n.startswith("retry")))
print("tenacity(同步) ->", sorted(n for n in dir(tenacity) if n.startswith("retry")))

print()
print("=== 2) 从 tenacity.asyncio 直接导入同步侧同名类会拿到哪一个")
from tenacity.asyncio import retry_if_result as from_async_pkg  # noqa: E402

print("tenacity.asyncio.retry_if_result 来自 ->", from_async_pkg.__module__)
print("tenacity.retry_if_result 来自 ->", tenacity.retry_if_result.__module__)
for name in (
    "retry_if_not_result",
    "retry_if_exception_type",
    "retry_if_exception_message",
    "retry_if_exception_cause_type",
    "retry_always",
    "retry_never",
):
    print(
        "  tenacity.asyncio.%-28s -> %s"
        % (name, hasattr(tenacity.asyncio, name) or hasattr(ar, name))
    )

print()
print("=== 3) 异步断言器配异步谓词：正常")


async def apred(v):
    return v < 0


async def call_with(retry_obj, label):
    calls = []

    @tenacity.retry(
        stop=tenacity.stop_after_attempt(3),
        retry=retry_obj,
        sleep=lambda s: asyncio.sleep(0),
    )
    async def f():
        calls.append(1)
        return -5

    try:
        r = await f()
    except BaseException as e:  # noqa: BLE001
        r = "抛出 %s: %s" % (type(e).__name__, str(e)[:40])
    print("  %-34s 实际调用次数=%d 结果=%r" % (label, len(calls), r))
    return calls


async def main():
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        await call_with(a_retry_if_result(apred), "异步 retry_if_result(异步谓词)")
        print("   警告:", [str(x.message)[:60] for x in w])

    print("=== 4) 同步 retry_if_result 配异步谓词（用户很容易写成）")
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        await call_with(retry_if_result(apred), "同步 retry_if_result(异步谓词)")
        print("   警告:", [str(x.message)[:70] for x in w])

    print("=== 5) 同步 retry_if_result 配同步谓词（对照组，期望 3 次）")
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        await call_with(retry_if_result(lambda v: v < 0), "同步 retry_if_result(同步谓词)")
        print("   警告:", [str(x.message)[:70] for x in w])

    print("=== 6) 异步侧组合器 vs 同步侧组合器：混搭时的判定")

    async def a_true(rs):
        return True

    def s_true(rs):
        return True

    mixed_async_comb = a_retry_if_result(apred) & s_true
    mixed_sync_comb = retry_if_result(lambda v: v < 0) & a_true
    print("  异步&同步 ->", type(mixed_async_comb).__module__)
    print("  同步&协程函数 ->", type(mixed_sync_comb).__module__)
    rs = tenacity.RetryCallState(retry_object=None, fn=None, args=(), kwargs={})
    rs.outcome = tenacity.Future.construct(1, -5, False)
    r1 = await mixed_async_comb(rs)
    print("  异步组合器 evaluate ->", r1)
    r2 = mixed_sync_comb(rs)
    if inspect.isawaitable(r2):
        r2 = await r2
    print("  同步组合器 evaluate -> %r (类型 %s)" % (r2, type(r2).__name__))

    print("=== 7) 组合器展平：三条链式与的 len(retries)")
    A = a_retry_if_result(apred)
    B = a_retry_if_result(apred)
    C = a_retry_if_result(apred)
    combo = A & B & C
    print("  异步 (A&B)&C ->", repr(combo)[:80], "len=", len(combo.retries))
    SA = retry_if_result(lambda v: True)
    SB = retry_if_result(lambda v: True)
    SC = retry_if_result(lambda v: True)
    scombo = SA & SB & SC
    print("  同步 (A&B)&C -> len=", len(scombo.retries))
    print("  异步 any 链 ->", len((A | B | C).retries))
    print("  同步 any 链 ->", len((SA | SB | SC).retries))


asyncio.run(main())
