FROM python:3.11-slim
ENV VALUE_STREAM_DATA_DIR=/data
VOLUME ["/data"]

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN python -m pip install --no-cache-dir . && rm -rf /app/src

EXPOSE 8080
CMD ["python", "-m", "uvicorn", "value_stream.service.app:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
