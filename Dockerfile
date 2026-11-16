FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CXSIGN_DATA=/data \
    TZ=Asia/Shanghai

WORKDIR /app

COPY pyproject.toml README.md ./
COPY cxsign ./cxsign
# 装 qr 额外依赖，让二维码截图解码开箱可用；嫌镜像大就改成 `pip install .`
RUN pip install --no-cache-dir ".[qr]"

RUN mkdir -p /data
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import httpx;httpx.get('http://127.0.0.1:8000/api/health',timeout=3)"

CMD ["python", "-m", "cxsign.server", "--host", "0.0.0.0", "--port", "8000"]
