"""
SSE (Server-Sent Events) 工具函数
"""

import asyncio
import json
from typing import Any, AsyncIterator

from fastapi import Request
from fastapi.responses import StreamingResponse

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def sse_event(event_type: str, data: dict[str, Any] | None = None, **kwargs: Any) -> str:
    """格式化 SSE 事件

    支持两种调用方式:
    - sse_event("error", {"message": "..."})
    - sse_event("error", message="...")
    """
    if data is None:
        data = kwargs
    else:
        data = {**data, **kwargs}
    return f"data: {json.dumps({'type': event_type, **data}, ensure_ascii=False)}\n\n"


def sse_log(message: str) -> str:
    """格式化 SSE 日志事件"""
    return sse_event("log", message=message)


def sse_response(generator_func) -> StreamingResponse:
    """创建 SSE 响应，接收生成器函数或生成器"""
    gen = generator_func() if callable(generator_func) else generator_func
    return StreamingResponse(gen, media_type="text/event-stream", headers=SSE_HEADERS)


async def sse_guard(request: Request, generator: AsyncIterator[str]) -> AsyncIterator[str]:
    """包装 SSE 生成器: 客户端断开连接时提前终止, 不再生成后续事件"""
    try:
        async for event in generator:
            if await request.is_disconnected():
                return
            yield event
    except asyncio.CancelledError:
        # 客户端断连触发的任务取消: 正常退出, 不吞掉
        raise
