FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml requirements.lock ./
COPY app ./app
RUN pip install --no-cache-dir -c requirements.lock . && useradd --uid 10001 --create-home ccai && mkdir -p /data/uploads && chown -R ccai:ccai /data /app
COPY alembic.ini ./
COPY migrations ./migrations
USER ccai
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
