FROM python:3.10-slim

ARG PANDOC_ARCH=amd64
ENV PANDOC_ARCH=$PANDOC_ARCH
ENV PATH="${PATH}:/root/.local/bin"

WORKDIR /app

# 安装依赖（合并指令、清理缓存、禁用推荐包）
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    gcc g++ curl build-essential libreoffice \
    wget procps vim fonts-wqy-zenhei \
    libglib2.0-0 libsm6 libxrender1 libxext6 libgl1 \
    && rm -rf /var/lib/apt/lists/*


# 安装 pandoc
RUN mkdir -p /opt/pandoc && \
    cd /opt/pandoc && \
    wget https://github.com/jgm/pandoc/releases/download/3.6.4/pandoc-3.6.4-linux-${PANDOC_ARCH}.tar.gz && \
    tar xvf pandoc-3.6.4-linux-${PANDOC_ARCH}.tar.gz && \
    cp pandoc-3.6.4/bin/pandoc /usr/bin/ && \
    rm -rf /opt/pandoc

# 安装 uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh

# 安装 Poetry
RUN curl -sSL https://install.python-poetry.org | python3 - --version 1.8.2

# 拷贝项目依赖文件
COPY ./pyproject.toml ./

# 安装 Python 依赖
RUN python -m pip install --upgrade pip && \
    pip install shapely==2.0.1 && \
    poetry config virtualenvs.create false && \
    poetry install --no-interaction --no-ansi --without dev

# 安装 NLTK 数据
RUN python -c "import nltk; nltk.download('punkt'); nltk.download('punkt_tab'); nltk.download('averaged_perceptron_tagger'); nltk.download('averaged_perceptron_tagger_eng')"

# 安装 playwright chromium
RUN playwright install chromium

COPY . .

CMD ["sh", "entrypoint.sh"]

