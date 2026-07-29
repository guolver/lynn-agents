# 文件解析沙箱 Dockerfile
# 构建一个最小化、安全加固的容器

FROM python:3.10-slim AS base

# 安全：创建非 root 用户
RUN useradd --create-home --shell /bin/bash parser

# 安装系统依赖（解析库需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    # OCR 支持（可选）
    # tesseract-ocr \
    # tesseract-ocr-chi-sim \
    # libmagic1 \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# 设置工作目录
WORKDIR /app

# 复制依赖文件
COPY requirements.txt .

# 安装 Python 依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY --chown=parser:parser . .

# 切换到非 root 用户
USER parser

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/health')" || exit 1

# 暴露端口
EXPOSE 8001

# 启动命令
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8001"]
