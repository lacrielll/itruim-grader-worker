FROM python:3.12-slim

ARG NUMPY_VERSION=2.1.3
RUN pip install --no-cache-dir "numpy==${NUMPY_VERSION}" \
    && useradd --create-home --uid 10001 grader

WORKDIR /submission
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/private:/canonical:/submission:/grader

ENTRYPOINT ["python", "/grader/sandbox_entry.py"]
