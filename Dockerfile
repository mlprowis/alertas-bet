FROM python:3.11-slim
WORKDIR /app
COPY requirements_railway.txt .
RUN pip install -r requirements_railway.txt
COPY . .
CMD ["python", "railway_main.py"]
