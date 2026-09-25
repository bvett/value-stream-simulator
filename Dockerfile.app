FROM node:22-bookworm-slim AS frontend
WORKDIR /build
COPY src/value_stream/app/frontend/package*.json ./
RUN npm ci
COPY src/value_stream/app/frontend/ ./
RUN npm run build

FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY --from=frontend /static ./src/value_stream/app/static
RUN python -m pip install --no-cache-dir . && rm -rf /app/src
EXPOSE 8081
CMD ["python", "-m", "value_stream.app", "--host", "0.0.0.0", "--port", "8081"]
