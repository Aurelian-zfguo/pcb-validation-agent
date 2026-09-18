# A 项目（PCB生产预投业务数据校验Agent）CLI 容器镜像
# 说明：容器只跑 CLI（python main.py），Tkinter GUI（gui.py）保留本地运行。
# A 项目无 torch 依赖，python:3.14-slim 足够，无需像 B 项目那样显式装 CPU 版 torch。

FROM python:3.14-slim

# 运行时环境：UTF-8 输出（Windows 中文乱码同理）、无缓冲、不写 pip 缓存
ENV PYTHONIOENCODING=utf-8 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 1) 依赖层：先只 COPY requirements.txt，后续源码改动不会失效这层缓存
COPY requirements.txt ./
RUN pip install -r requirements.txt

# 2) 源码层：只打包运行时必需文件（gui.py / tests/ / docs/ 不进镜像）
COPY main.py ./
COPY src/ ./src/
COPY config/ ./config/

# 3) 运行时目录：作为 volume 挂载点（output/ 报告、logs/ 日志、data/ 输入）
RUN mkdir -p /app/output /app/logs /app/data

# 入口：docker run pcb-validator --工厂 金州厂 ... 直接传参给 main.py
ENTRYPOINT ["python", "main.py"]
