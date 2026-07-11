FROM python:3.11-slim

WORKDIR /app

# antiword: offline extractor for legacy binary .doc (Word 97-2003) — the
# census-validated path (python-docx cannot read binary .doc). LibreOffice is
# deliberately NOT installed (too heavy); antiword is the minimal, validated tool.
RUN apt-get update && apt-get install -y --no-install-recommends git curl antiword \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-dev.txt

COPY . .

ENV PYTHONPATH=/app PYTHONUNBUFFERED=1

CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
