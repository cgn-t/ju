# NITRO-uyumlu MOCK ADC — çok-mimarili python taban (arm64 NATIVE, emülasyon yok).
# Gerçek NetScaler değildir; CPX Apple Silicon'da emüle edilemediği için yerel demo köprüsü.
FROM python:3.12-alpine
WORKDIR /app
COPY mock.py .
EXPOSE 9080 443
CMD ["python", "-u", "mock.py"]
