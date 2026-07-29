# 文件解析沙箱设计文档

## 概述

本文档描述文件解析沙箱服务的设计方案。该服务将文件解析逻辑隔离在独立容器中运行，防止恶意文件攻击主服务。

## 背景

### 为什么需要沙箱

平台需要支持多种文件格式的上传和解析：

| 格式 | 风险等级 | 威胁 |
|------|----------|------|
| PDF | 中 | 资源耗尽、解析库漏洞 |
| DOCX/XLSX | 中 | XML 炸弹、宏代码 |
| HTML | 中 | XSS、恶意脚本 |
| ZIP/TAR | 高 | Zip 炸弹 (42KB → 4.5PB) |
| 图片 | 中 | 图像处理库漏洞 |

直接在主服务中解析这些文件存在以下风险：

1. **资源耗尽**：恶意文件消耗大量 CPU/内存，导致服务不可用
2. **代码执行**：利用解析库漏洞执行任意代码
3. **数据泄露**：攻破主服务后可访问数据库和 API 密钥

### 沙箱的安全边界

```
┌─────────────────────────────────────────────────────────────┐
│                     信任边界                                 │
│  ┌───────────────────────────────────────────────────────┐  │
│  │                  主服务 (FastAPI)                      │  │
│  │  - 数据库连接                                          │  │
│  │  - API 密钥 (DeepSeek, etc.)                          │  │
│  │  - 用户会话                                            │  │
│  │  - 业务逻辑                                            │  │
│  └───────────────────────────────────────────────────────┘  │
│                          │                                  │
│                   HTTP (内网)                               │
│                          │                                  │
│  ┌───────────────────────────────────────────────────────┐  │
│  │              文件解析沙箱 (隔离容器)                     │  │
│  │  - 无数据库访问                                        │  │
│  │  - 无 API 密钥                                        │  │
│  │  - 无外网访问                                          │  │
│  │  - 资源受限 (CPU/内存/磁盘)                            │  │
│  │  - 只读文件系统                                        │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

## 架构设计

### 整体架构

```
用户上传文件
     │
     ▼
┌─────────────────┐
│   主服务 API     │
│  /upload        │
└────────┬────────┘
         │ 1. 基础校验 (大小、扩展名)
         │
         ▼
┌─────────────────┐
│ FileParserClient│
│                 │──── HTTP POST ────┐
└─────────────────┘                   │
                                      ▼
                        ┌─────────────────────────┐
                        │    文件解析沙箱容器       │
                        │  ┌───────────────────┐  │
                        │  │ 格式检测           │  │
                        │  └─────────┬─────────┘  │
                        │            │            │
                        │  ┌─────────▼─────────┐  │
                        │  │ 安全检查           │  │
                        │  │ - 文件大小         │  │
                        │  │ - 魔数验证         │  │
                        │  │ - 压缩比检测       │  │
                        │  └─────────┬─────────┘  │
                        │            │            │
                        │  ┌─────────▼─────────┐  │
                        │  │ 格式解析器         │  │
                        │  │ - PDF Parser      │  │
                        │  │ - Office Parser   │  │
                        │  │ - HTML Parser     │  │
                        │  │ - Archive Parser  │  │
                        │  │ - Image OCR       │  │
                        │  └─────────┬─────────┘  │
                        │            │            │
                        │  ┌─────────▼─────────┐  │
                        │  │ 文本提取 & 清洗    │  │
                        │  └───────────────────┘  │
                        └─────────────────────────┘
                                      │
                                      ▼
                              返回纯文本结果
                                      │
         ┌────────────────────────────┘
         │
         ▼
┌─────────────────┐
│   主服务继续     │
│   业务处理       │
│  (LLM 分析等)   │
└─────────────────┘
```

### 项目结构

```
agent_hub/
├── file_parser/                    # 沙箱服务（独立部署）
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── app.py                      # FastAPI 入口
│   ├── config.py                   # 配置（限制参数）
│   ├── security.py                 # 安全检查
│   ├── parsers/
│   │   ├── __init__.py
│   │   ├── base.py                 # 解析器基类
│   │   ├── pdf.py                  # PDF 解析
│   │   ├── office.py               # DOCX/XLSX 解析
│   │   ├── html.py                 # HTML 解析
│   │   ├── archive.py              # ZIP/TAR 解析
│   │   ├── image.py                # 图片 OCR
│   │   └── text.py                 # TXT/MD/JSON
│   └── tests/
│       ├── test_parsers.py
│       └── fixtures/               # 测试文件
│
├── core/
│   └── file_parser_client.py       # 主服务调用客户端
```

## API 设计

### 沙箱服务 API

#### POST /parse

解析上传的文件，返回提取的文本内容。

**请求**

```
Content-Type: multipart/form-data

file: <binary>          # 文件内容
filename: string        # 原始文件名（用于格式检测）
options: JSON (可选)    # 解析选项
```

**响应**

```json
{
  "success": true,
  "data": {
    "text": "提取的纯文本内容...",
    "chunks": [
      {
        "title": "Section 1",
        "content": "...",
        "metadata": {}
      }
    ],
    "metadata": {
      "format": "pdf",
      "pages": 5,
      "size_bytes": 102400,
      "parse_time_ms": 234
    }
  }
}
```

**错误响应**

```json
{
  "success": false,
  "error": {
    "code": "FILE_TOO_LARGE",
    "message": "File exceeds 10MB limit"
  }
}
```

#### GET /health

健康检查端点。

```json
{
  "status": "healthy",
  "version": "1.0.0"
}
```

#### GET /formats

返回支持的文件格式列表。

```json
{
  "formats": [
    {"extension": ".pdf", "mime_type": "application/pdf", "max_size_mb": 10},
    {"extension": ".docx", "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "max_size_mb": 10},
    {"extension": ".xlsx", "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "max_size_mb": 10},
    {"extension": ".html", "mime_type": "text/html", "max_size_mb": 5},
    {"extension": ".zip", "mime_type": "application/zip", "max_size_mb": 50},
    {"extension": ".png", "mime_type": "image/png", "max_size_mb": 10},
    {"extension": ".jpg", "mime_type": "image/jpeg", "max_size_mb": 10}
  ]
}
```

## 安全措施

### 1. 容器级隔离

```yaml
# docker-compose.yml
services:
  file-parser:
    build: ./agent_hub/file_parser

    # 资源限制
    mem_limit: 512m
    mem_reservation: 256m
    cpus: 1
    pids_limit: 100

    # 安全选项
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    read_only: true

    # 临时目录（用于解析过程）
    tmpfs:
      - /tmp:size=100M,mode=1777

    # 网络隔离
    networks:
      - parser-internal
    # 无外网访问

    # 非 root 用户
    user: "1000:1000"
```

### 2. 应用级防护

```python
# config.py
class ParserConfig:
    # 文件大小限制
    MAX_FILE_SIZE_MB = 10
    MAX_ARCHIVE_SIZE_MB = 50

    # 解析限制
    MAX_PDF_PAGES = 100
    MAX_ARCHIVE_FILES = 100
    MAX_ARCHIVE_RATIO = 10          # 压缩比限制（防 zip 炸弹）
    MAX_XML_DEPTH = 20              # 防 XML 炸弹
    MAX_IMAGE_PIXELS = 50_000_000   # 50MP

    # 超时
    PARSE_TIMEOUT_SECONDS = 30

    # 禁用危险功能
    DISABLE_OFFICE_MACROS = True
    DISABLE_PDF_JAVASCRIPT = True
    DISABLE_HTML_SCRIPTS = True
```

### 3. 文件类型验证

```python
# security.py
import magic

ALLOWED_MIMES = {
    'application/pdf',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'text/html',
    'text/plain',
    'text/markdown',
    'application/json',
    'application/zip',
    'image/png',
    'image/jpeg',
}

def validate_file(file_bytes: bytes, filename: str) -> str:
    """验证文件类型，返回 MIME type"""
    # 1. 检查文件大小
    if len(file_bytes) > MAX_FILE_SIZE_MB * 1024 * 1024:
        raise FileTooLargeError()

    # 2. 检查魔数（真实文件类型）
    detected_mime = magic.from_buffer(file_bytes, mime=True)

    # 3. 验证扩展名与内容匹配
    ext_mime = get_mime_from_extension(filename)
    if detected_mime != ext_mime:
        raise MimeTypeMismatchError(f"Extension suggests {ext_mime}, but content is {detected_mime}")

    # 4. 检查是否允许
    if detected_mime not in ALLOWED_MIMES:
        raise UnsupportedFormatError(detected_mime)

    return detected_mime
```

### 4. Zip 炸弹防护

```python
# parsers/archive.py
import zipfile

def safe_extract_zip(file_bytes: bytes, max_ratio: int = 10) -> list[tuple[str, bytes]]:
    """安全解压 ZIP，防止 zip 炸弹"""
    compressed_size = len(file_bytes)
    max_uncompressed = compressed_size * max_ratio

    extracted = []
    total_size = 0

    with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
        # 检查文件数量
        if len(zf.namelist()) > MAX_ARCHIVE_FILES:
            raise TooManyFilesError()

        for info in zf.infolist():
            # 跳过目录
            if info.is_dir():
                continue

            # 检查单文件大小
            if info.file_size > MAX_FILE_SIZE_MB * 1024 * 1024:
                raise FileTooLargeError(info.filename)

            # 检查累计大小（防 zip 炸弹）
            total_size += info.file_size
            if total_size > max_uncompressed:
                raise ZipBombDetectedError(
                    f"Compression ratio exceeds {max_ratio}x limit"
                )

            # 安全：逐个提取
            content = zf.read(info.filename)
            extracted.append((info.filename, content))

    return extracted
```

## 部署配置

### Docker Compose

```yaml
# docker-compose.yml
version: "3.8"

services:
  api:
    build: .
    ports:
      - "8000:8000"
    environment:
      - FILE_PARSER_URL=http://file-parser:8001
    depends_on:
      - file-parser
    networks:
      - default
      - parser-internal

  file-parser:
    build: ./agent_hub/file_parser
    expose:
      - "8001"
    mem_limit: 512m
    cpus: 1
    read_only: true
    tmpfs:
      - /tmp:size=100M
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    networks:
      - parser-internal
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8001/health"]
      interval: 30s
      timeout: 10s
      retries: 3

networks:
  parser-internal:
    internal: true  # 无外网访问
```

### Kubernetes (可选)

```yaml
# k8s/file-parser-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: file-parser
spec:
  replicas: 2
  template:
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
      containers:
        - name: file-parser
          image: agent-hub/file-parser:latest
          resources:
            limits:
              memory: "512Mi"
              cpu: "1"
            requests:
              memory: "256Mi"
              cpu: "0.5"
          securityContext:
            readOnlyRootFilesystem: true
            allowPrivilegeEscalation: false
            capabilities:
              drop:
                - ALL
          volumeMounts:
            - name: tmp
              mountPath: /tmp
      volumes:
        - name: tmp
          emptyDir:
            sizeLimit: 100Mi
```

## 主服务集成

### FileParserClient

```python
# core/file_parser_client.py
from __future__ import annotations

import httpx
from dataclasses import dataclass
from typing import Any


@dataclass
class ParseResult:
    """文件解析结果"""
    text: str
    chunks: list[dict[str, Any]]
    metadata: dict[str, Any]


class FileParserError(Exception):
    """文件解析错误"""
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class FileParserClient:
    """文件解析沙箱客户端"""

    def __init__(
        self,
        base_url: str = "http://file-parser:8001",
        timeout: float = 35.0,
    ):
        self.base_url = base_url
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
            )
        return self._client

    async def parse(
        self,
        file_bytes: bytes,
        filename: str,
        options: dict[str, Any] | None = None,
    ) -> ParseResult:
        """解析文件，返回提取的文本"""
        client = await self._get_client()

        response = await client.post(
            "/parse",
            files={"file": (filename, file_bytes)},
            data={"options": json.dumps(options or {})},
        )

        result = response.json()

        if not result.get("success"):
            error = result.get("error", {})
            raise FileParserError(
                code=error.get("code", "UNKNOWN"),
                message=error.get("message", "Parse failed"),
            )

        data = result["data"]
        return ParseResult(
            text=data["text"],
            chunks=data.get("chunks", []),
            metadata=data.get("metadata", {}),
        )

    async def health(self) -> bool:
        """检查沙箱服务健康状态"""
        try:
            client = await self._get_client()
            response = await client.get("/health")
            return response.status_code == 200
        except Exception:
            return False

    async def close(self):
        """关闭客户端连接"""
        if self._client:
            await self._client.aclose()
            self._client = None
```

### 在现有代码中使用

```python
# agents/global_part_time/resume_parser.py
from agent_hub.core.file_parser_client import FileParserClient

async def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """通过沙箱服务提取 PDF 文本"""
    client = FileParserClient()
    try:
        result = await client.parse(pdf_bytes, "resume.pdf")
        return result.text
    finally:
        await client.close()
```

## 监控与告警

### 关键指标

| 指标 | 告警阈值 | 说明 |
|------|----------|------|
| `parser_request_duration_seconds` | P99 > 10s | 解析耗时 |
| `parser_memory_usage_bytes` | > 400MB | 内存使用 |
| `parser_error_rate` | > 5% | 错误率 |
| `parser_zip_bomb_detected_total` | > 0 | Zip 炸弹检测 |
| `parser_file_rejected_total` | - | 被拒绝的文件 |

### 日志格式

```json
{
  "timestamp": "2024-01-15T10:30:00Z",
  "level": "info",
  "event": "file_parsed",
  "filename": "resume.pdf",
  "format": "pdf",
  "size_bytes": 102400,
  "parse_time_ms": 234,
  "pages": 5
}
```

```json
{
  "timestamp": "2024-01-15T10:31:00Z",
  "level": "warn",
  "event": "file_rejected",
  "filename": "malicious.zip",
  "reason": "zip_bomb_detected",
  "compression_ratio": 1000
}
```

## 实施计划

### 第一阶段：基础框架

- [ ] 创建 file_parser 服务目录结构
- [ ] 实现 PDF/TXT/MD/JSON 解析器（迁移现有代码）
- [ ] 添加基础安全检查（大小、类型）
- [ ] 编写 Dockerfile 和 docker-compose 配置
- [ ] 实现 FileParserClient

### 第二阶段：扩展格式

- [ ] 添加 DOCX/XLSX 解析器
- [ ] 添加 HTML 解析器
- [ ] 添加 ZIP 解析器（含 zip 炸弹防护）
- [ ] 添加图片 OCR 支持

### 第三阶段：加固与监控

- [ ] 添加 Prometheus 指标
- [ ] 添加详细日志
- [ ] 编写安全测试用例
- [ ] 添加 Kubernetes 部署配置

## 参考资料

- [OWASP File Upload Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html)
- [Docker Security Best Practices](https://docs.docker.com/develop/security-best-practices/)
- [Zip Bomb 原理](https://en.wikipedia.org/wiki/Zip_bomb)
