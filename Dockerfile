FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip && \
    pip install -r /app/requirements.txt

COPY . /app

EXPOSE 8501

# Served behind the shared ALB at /widgets/stats/. Streamlit's baseUrlPath
# rewrites all asset + WebSocket URLs under that prefix (its equivalent of
# Dash's url_base_pathname). CORS/XSRF disabled so it can run inside the
# dashboard iframe. One replica keeps WebSocket sessions on a single task.
CMD ["sh", "-c", "streamlit run widget.py \
  --server.port=8501 \
  --server.address=0.0.0.0 \
  --server.baseUrlPath=widgets/stats \
  --server.headless=true \
  --server.enableCORS=false \
  --server.enableXsrfProtection=false"]
