# JUMBO — TEK CONTAINER (all-in-one): React SPA + nginx + FastAPI/uvicorn.
#   nginx :8080  →  ÖN KAPI (önyüz): /api → 127.0.0.1:5000 (uvicorn) , /* → frontend :9080
#   nginx :9080  →  React SPA statik (frontend)
#   uvicorn :5000 → backend
#   supervisord her iki süreci yönetir; imaj OpenShift arbitrary-UID uyumludur.
# MSSQL bağlantısı pymssql ile ve MSSQL_* ENV değişkenlerinden kurulur (aşağıya bkz.).
# Build context = repo kökü:  docker build -t jumbo:latest .

# --- 1) frontend derleme ---
FROM node:24 AS build
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build            # -> /app/dist

# --- 2) çalışma imajı: python + nginx (MSSQL için pymssql; ODBC sürücüsü GEREKMEZ) ---
FROM python:3.13-slim-bullseye
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

# pymssql pip tekerlekleri FreeTDS'i kendi içinde barındırır → Microsoft ODBC deposu,
# imza/SHA1 ve libgssapi derdi YOK. Sadece nginx kurulur.
RUN apt-get update \
 && apt-get install -y --no-install-recommends nginx ca-certificates \
 && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install -r requirements.txt && pip install supervisor

COPY backend/ ./
COPY --from=build /app/dist /usr/share/nginx/html
COPY deploy/nginx-allinone.conf /etc/nginx/nginx.conf
COPY deploy/supervisord.conf    /etc/supervisord.conf

# MSSQL bağlantısı ENV'den kurulur (kod: config.effective_database_url → mssql+pymssql://...).
# VARSAYILAN = yerel dev veritabanı (jumbo-mssql). Böylece ekstra -e olmadan MSSQL'e bağlanır:
#   docker run --network jumbo-net -p 9080:9080 jumbo:latest
# (hostname 'jumbo-mssql' yalnız jumbo-net ağında çözülür.)
# Yalnız hassas OLMAYAN varsayılanlar imaja gömülür. MSSQL_PASSWORD ve JWT_SECRET imaja
# GÖMÜLMEZ — çalışma anında `-e` / Kubernetes Secret ile verilir (jumbo-k8s.yaml örneğine bakın).
ENV MSSQL_HOST="jumbo-mssql" \
    MSSQL_PORT="1433" \
    MSSQL_USER="sa" \
    MSSQL_DB="JUMBO2"

# OpenShift arbitrary-UID uyumu: yazılabilecek dizinleri GID 0'a aç (grup izni = sahip izni).
# Rastgele UID daima GID 0 üyesidir → bu dizinlere yazabilir. pid/temp zaten /tmp'de (herkese açık).
RUN chgrp -R 0 /app /usr/share/nginx/html /var/lib/nginx /var/log/nginx \
 && chmod -R g=u /app /usr/share/nginx/html /var/lib/nginx /var/log/nginx

# Yerel docker için non-root çalıştığını garanti et (OpenShift bu UID'yi zaten override eder).
USER 1001

EXPOSE 8080 9080
CMD ["supervisord", "-c", "/etc/supervisord.conf"]
