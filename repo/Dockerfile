FROM python:3.10-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /app/data /app/app/static/uploads /app/watch_folder /app/quarantine
ENV FLASK_APP=app:create_app
EXPOSE 5000
CMD ["sh", "-c", "flask db-init && gunicorn -b 0.0.0.0:5000 'app:create_app()'"]
