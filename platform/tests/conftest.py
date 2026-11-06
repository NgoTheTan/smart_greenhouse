"""Cấu hình pytest: bật SelectorEventLoop trên Windows để aiomqtt chạy được trong test tích hợp."""

import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

