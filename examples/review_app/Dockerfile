FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml README.md LICENSE MANIFEST.in ./
COPY src ./src
COPY examples/review_app/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir . -r requirements.txt && useradd --create-home --uid 10001 appuser \
    && mkdir /state && chown appuser:appuser /state
COPY --chown=appuser:appuser examples/review_app ./examples/review_app
COPY --chown=appuser:appuser docs/logo.png ./examples/review_app/logo.png
USER appuser
EXPOSE 8000
CMD ["uvicorn", "examples.review_app.app:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
