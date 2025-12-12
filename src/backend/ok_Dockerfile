FROM cr.dataelem.com/dataelement/bisheng-backend:v2.2.0

WORKDIR /app

COPY ./ ./

# 修复后命令（使用 pip 安装，自动注册到 site-packages）
RUN pip install --no-cache-dir SQLAlchemy==2.0.39 && \
    pip install --no-cache-dir /app/soft/dmpython-2.5.30-cp310-cp310-linux_x86_64.whl && \
    pip install --no-cache-dir /app/soft/dmSQLAlchemy2.0/ && \
    pip install --no-cache-dir /app/soft/dmAsync/ && \
    rm -rf /root/.cache/pip  # 清理缓存，减少镜像体积

ENV LD_LIBRARY_PATH "/usr/lib64:$LD_LIBRARY_PATH:/app/soft/bin/:/app/soft/bin/dependencies"

#RUN poetry config virtualenvs.create false
#RUN poetry update --without dev

# patch langchain-openai lib. remove this when langchain-openai support reasoning_content
#RUN patch -p1 < /app/bisheng/patches/langchain_openai.patch /usr/local/lib/python3.10/site-packages/langchain_openai/chat_models/base.py


CMD ["sh entrypoint.sh"]
