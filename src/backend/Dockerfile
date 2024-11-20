FROM python:3.10-slim

WORKDIR /app

RUN echo \
    deb https://mirrors.aliyun.com/debian/ bookworm main non-free non-free-firmware contrib \
    deb-src https://mirrors.aliyun.com/debian/ bookworm main non-free non-free-firmware contrib \
    deb https://mirrors.aliyun.com/debian-security/ bookworm-security main \
    deb-src https://mirrors.aliyun.com/debian-security/ bookworm-security main \
    deb https://mirrors.aliyun.com/debian/ bookworm-updates main non-free non-free-firmware contrib \
    deb-src https://mirrors.aliyun.com/debian/ bookworm-updates main non-free non-free-firmware contrib \
    deb https://mirrors.aliyun.com/debian/ bookworm-backports main non-free non-free-firmware contrib \
    deb-src https://mirrors.aliyun.com/debian/ bookworm-backports main non-free non-free-firmware contrib \
    > /etc/apt/sources.list


# Install Poetry
RUN apt-get update && apt-get install gcc g++ curl build-essential postgresql-server-dev-all -y
RUN apt-get update && apt-get install procps -y
# Install font
RUN apt install vim fonts-wqy-zenhei -y
# opencv
RUN apt-get update && apt-get install -y libglib2.0-0 libsm6 libxrender1 libxext6 libgl1
RUN curl -sSL https://install.python-poetry.org | python3 - --version 1.8.2
# # Add Poetry to PATH
ENV PATH="${PATH}:/root/.local/bin"
# # Copy the pyproject.toml and poetry.lock files
# COPY poetry.lock pyproject.toml ./
# Copy the rest of the application codes
COPY ./ ./

# Install NLTK data
RUN mv -f ./nltk_data /root/nltk_data/

RUN python -m pip install --upgrade pip && \
    pip install shapely==2.0.1

# Install dependencies
RUN poetry config virtualenvs.create false
RUN poetry install --no-interaction --no-ansi --without dev

CMD ["uvicorn", "bisheng.main:app", "--workers", "2",  "--host", "0.0.0.0", "--port", "7860"]
