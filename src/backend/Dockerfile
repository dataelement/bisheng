FROM python:3.10-slim

WORKDIR /app

# Install Poetry
RUN apt-get update && apt-get install gcc g++ curl build-essential postgresql-server-dev-all -y
RUN apt-get update && apt-get install procps -y
RUN curl -sSL https://install.python-poetry.org | python3 -
# # Add Poetry to PATH
ENV PATH="${PATH}:/root/.local/bin"
# # Copy the pyproject.toml and poetry.lock files
COPY poetry.lock pyproject.toml ./
# Copy the rest of the application codes
COPY ./ ./

RUN pip config set global.index-url http://public:26rS9HRxDqaVy5T@192.168.106.8:6081/repository/pypi-group/simple
RUN pip config set global.trusted-host 192.168.106.8

RUN python -m pip install --upgrade pip && \
    pip install gunicorn && \
    pip install shapely==2.0.1 && \
    pip install langchain_contrib==0.0.1

# Install dependencies
RUN poetry config virtualenvs.create false
RUN poetry install --no-interaction --no-ansi

CMD ["uvicorn", "bisheng.main:app", "--workers", "20",  "--host", "0.0.0.0", "--port", "7860"]