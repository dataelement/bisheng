FROM dataelement/bisheng-backend:v2.4.0-zl-arm64 
# 基于基础镜像构建，包含 Python 3.10 和必要的系统依赖

WORKDIR /app

COPY ./ ./

# 安装依赖 + 补丁（合并为一层）
# 需要本地的 whl 包和源码包，确保它们在构建上下文中
RUN pip install --no-cache-dir SQLAlchemy && \
    pip install --no-cache-dir ./dmpython-2.5.30-cp310-cp310-manylinux2014_aarch64.whl && \
    pip install --no-cache-dir ./dmSQLAlchemy2.0/ && \
    pip install --no-cache-dir ./dmAsync/ && \
    rm -rf /root/.cache/pip

ENV LD_LIBRARY_PATH="/usr/lib:/app/soft/bin/:/app/soft/bin/dependencies"
ENV DM_HOME="/usr/local/lib/python3.10/site-packages/dmssl/"
# 最后拷贝代码（利用构建缓存）
COPY . .

# 正确的启动命令
CMD ["sh", "entrypoint.sh"]