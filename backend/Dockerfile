FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cu128

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir torch --index-url ${TORCH_INDEX_URL} \
    && python -m pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]