FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 EPOCHLAB_DATA=/data
RUN useradd -u 10001 -m epochlab
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY epochlab ./epochlab
COPY web ./web
COPY scripts ./scripts
# files unpacked from a zip made on Windows can arrive as 0700: make the code readable by the app user
RUN chmod -R a+rX /app
RUN mkdir -p /data && chown epochlab /data
USER epochlab
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health')"
CMD ["uvicorn", "epochlab.api:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
# Forwarded headers are trusted only from FORWARDED_ALLOW_IPS (uvicorn default 127.0.0.1). Never "*": a client could
# then pretend to be 127.0.0.1 with its own X-Forwarded-For header.
