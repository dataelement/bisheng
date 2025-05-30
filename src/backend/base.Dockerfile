FROM python:3.10-slim

ARG PANDOC_ARCH=amd64
ENV PANDOC_ARCH=$PANDOC_ARCH

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



# Install lib
RUN apt-get update && apt-get install gcc g++ curl build-essential postgresql-server-dev-all wget libreoffice -y
RUN apt-get update && apt-get install procps -y

# Install pandoc
RUN mkdir -p /opt/pandoc \
    && cd /opt/pandoc \
    && wget https://github.com/jgm/pandoc/releases/download/3.6.4/pandoc-3.6.4-linux-${PANDOC_ARCH}.tar.gz \
    && tar xvf pandoc-3.6.4-linux-${PANDOC_ARCH}.tar.gz \
    && cd pandoc-3.6.4 \
    && cp bin/pandoc /usr/bin/ \
    && cd ..

# Install font
RUN apt install vim fonts-wqy-zenhei -y
# opencv
RUN apt-get update && apt-get install -y libglib2.0-0 libsm6 libxrender1 libxext6 libgl1
RUN curl -sSL https://install.python-poetry.org | python3 - --version 1.8.2
# # Add Poetry to PATH
ENV PATH="${PATH}:/root/.local/bin"

COPY ./pyproject.toml ./

RUN python -m pip install --upgrade pip && \
    pip install shapely==2.0.1

# Install dependencies
RUN poetry config virtualenvs.create false
RUN poetry install --no-interaction --no-ansi --without dev

# install nltk_data
RUN python -c "import nltk; nltk.download('punkt'); nltk.download('punkt_tab'); nltk.download('averaged_perceptron_tagger'); nltk.download('averaged_perceptron_tagger_eng'); "

CMD ["sh entrypoint.sh"]
