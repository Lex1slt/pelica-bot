# 佩丽卡监督 —— 生产镜像（Ubuntu 22.04 级别的 glibc 环境，Python 3.11 + Node 18+）
# 2核4G 云服务器可用；语料、数据库、日志均为挂载卷，镜像本身无状态。

FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Shanghai \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs npm tzdata ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先装 Python 依赖（利用层缓存）
COPY requirements.txt ./
RUN pip install -r requirements.txt

# wechaty 依赖单独一层：mock 模式不阻塞构建
COPY bridges/wechaty/package.json bridges/wechaty/
RUN cd bridges/wechaty && (npm install --omit=dev --no-audit --no-fund || \
    echo "[build] wechaty 依赖安装失败（mock 模式不受影响；生产 wechaty 模式请在服务器上重试 npm install）")

# 项目代码（.dockerignore 已排除语料/数据/日志/密钥）
COPY . .

VOLUME ["/app/data", "/app/logs"]
EXPOSE 9000

HEALTHCHECK --interval=60s --timeout=10s --start-period=60s --retries=3 \
    CMD python scripts/healthcheck.py

# 默认 mock 模式不会发任何真实消息；生产在 .env 设 BRIDGE_MODE=wechaty
CMD ["python", "main.py"]
