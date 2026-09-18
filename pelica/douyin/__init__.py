"""抖音管道包：链接检测 -> 无水印解析 -> 下载 -> 经桥接发送。

纯本地处理（HTTP + 正则 + 下载），任何一步都不调用大模型。
"""

from pelica.douyin.parser import DouyinError, DouyinParser, DouyinResult
from pelica.douyin.pipeline import DouyinPipeline

__all__ = ["DouyinError", "DouyinParser", "DouyinPipeline", "DouyinResult"]
