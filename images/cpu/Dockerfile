FROM python:3.12-slim

ARG NUMPY_VERSION=2.1.3
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=120
RUN python -m pip install --no-cache-dir --retries 10 --timeout 120 "numpy==${NUMPY_VERSION}" \
    && useradd --create-home --uid 10001 grader

WORKDIR /submission
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/private:/canonical:/submission:/grader

ENTRYPOINT ["python", "/grader/sandbox_entry.py"]
