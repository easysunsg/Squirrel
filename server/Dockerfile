FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml ./
RUN uv pip install --system --no-cache-dir \
    fastapi uvicorn pydantic pydantic-settings httpx langgraph chromadb python-multipart

COPY . .

RUN mkdir -p /data /storage

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
