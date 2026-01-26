FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt gunicorn

COPY . .

RUN mkdir -p staticfiles media

# Make entrypoint executable
RUN chmod +x entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["gunicorn", "chat_bot_mac.wsgi:application", "--bind", "0.0.0.0:8000"]
