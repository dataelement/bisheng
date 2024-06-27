FROM python:3.10-slim

WORKDIR /app

# Install Poetry
RUN apt-get update && apt-get install gcc g++ curl build-essential postgresql-server-dev-all -y
RUN apt-get update && apt-get install procps -y
# Install font
RUN apt install fonts-wqy-zenhei -y
# opencv
RUN apt-get install -y libglib2.0-0 libsm6 libxrender1 libxext6 libgl1
RUN curl -sSL https://install.python-poetry.org | python3 -
# # Add Poetry to PATH
ENV PATH="${PATH}:/root/.local/bin"
# # Copy the pyproject.toml and poetry.lock files
# COPY poetry.lock pyproject.toml ./
# Copy the rest of the application codes
COPY ./ ./

RUN python -m pip install --upgrade pip && \
    pip install shapely==2.0.1 

# Install dependencies
RUN poetry config virtualenvs.create false
RUN poetry install --no-interaction --no-ansi --without dev

CMD ["uvicorn", "bisheng.main:app", "--workers", "2",  "--host", "0.0.0.0", "--port", "7860"]
