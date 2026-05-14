---
name: 开发规范 (Coding Guidelines)
description: 规范当前 Python (FastAPI + SQLAlchemy) 项目的代码开发标准，涵盖编码风格、分层架构、数据库及异常处理等。
---

# 开发规范

本 Skill 用于指导当前项目的代码开发，确保代码风格统一、结构清晰且易于维护。在协助进行代码生成、重构或修改时，请务必遵循以下规范：

## 1. 编码风格 (Code Style)
- **PEP 8**：严格遵循 PEP 8 规范。
- **类型提示 (Type Hints)**：强制使用类型注解。所有的函数、方法参数及返回值必须明确指定类型，以支持静态检查和代码智能感知。
- **命名规范**：
  - 包名/模块名/变量名/函数名：`snake_case`
  - 类名：`PascalCase`
  - 常量名：`UPPER_SNAKE_CASE`
- **代码格式化**：假设项目使用了 `black`、`ruff` 或 `isort`，在编写代码时应保持与之相符的格式。

## 2. 架构设计与分层 (Architecture)
- 目录结构：
    - `业务模块目录`：每个业务模块应有独立的目录
        - `api`：定义与外部交互的接口（如 FastAPI 路由）
            - `endpoints`：具体的 API 端点实现
            - `dependencies.py`：定义 API 层的依赖项（如service 层的依赖）
            - `router.py`：定义 API 路由
        - `domain`：核心业务逻辑和领域模型
            - `models`：定义数据库模型（SQLModel）
            - `services`：定义业务服务类，封装核心业务逻辑
            - `repositories`：定义数据访问层，封装数据库操作
                - `implementations`：具体的 Repository 实现，应继承 `BaseRepositoryImpl[ModelClass, IDType], RepositoryInterface`
                - `interfaces`：定义 Repository 接口，应继承 `BaseRepository[ModelClass, IDType], ABC`
            - `schemas`：定义 Pydantic 模型，用于数据验证和序列化


## 3. 数据库与 ORM (SQLAlchemy & Alembic)
- 表结构变动：所有数据库表结构的增删改，必须通过 **Alembic** 生成迁移文件（如 `alembic revision --autogenerate`），禁止直接手动修改数据库表结构。
    - versions 目录所在路径：`bisheng/core/database/alembic/versions`
    - 可以阅读 `bisheng/core/database/alembic/README.md`
- 数据库操作：所有数据库的增删改查必须通过  SQLModel 或 SQLAlchemy ORM 模型进行，止禁直接使用原生 SQL 语句。
    - 数据库会话（Session）应通过依赖注入的方式获取,或者通过装饰器（如 `@db_session`）进行管理，确保事务的一致性和正确的资源释放。
- 模型定义：使用SQLModel 定义数据库模型，确保与数据库表结构一致，并且支持 Pydantic 的数据验证,使用sa_column等方式定义字段属性。
    - 模型类应放在 `models` 模块中，且每个模型类应有明确的表名（`__tablename__`）和字段定义。
    - 模型字段应使用 SQLModel 的 `Field` 函数进行定义，明确字段类型、默认值、索引等属性。
- 查询规范：尽量使用 SQLModel 的查询接口进行数据操作，避免直接使用原生 SQL 语句。对于复杂查询，可以在 Repository 层封装成方法，并提供清晰的接口。
    - 如果有需要查询多张表的业务逻辑，尽量使用 JOIN 或子查询的方式进行，而不是在 Python 代码中进行多次查询和数据处理。
    - 对于分页查询，建议使用 SQLModel 的分页功能，或者在 Repository 层封装一个通用的分页方法，以提高代码复用性和性能。
    - 对于批量操作（如批量插入、更新），建议使用 SQLModel 的批量操作接口，以提高效率和性能。

## 4. 异常处理与日志 (Exception Handling & Logging)
- **分业务自定义异常**：每个业务模块应定义自己的异常类，继承自一个公共的基类（如 `BaseErrorCode`）
    - 在 `bisheng/common/errcode` 目录下定义不同业务的异常文件，如 `user.py`、`knowledge.py` 等，每个文件中定义该业务相关的异常类。
    - 自定义异常类集成 `BaseErrorCode`，并设置Code、Msg属性，以便在 API 层统一处理和返回错误响应。
    - 在业务逻辑中，遇到错误情况时应抛出相应的自定义异常，`raise UserNotFoundError()`，而不是直接返回错误码或字符串。API 层应捕获这些异常，并根据异常的 Code 和 Msg 生成统一的错误响应。
- **日志记录**：在关键业务流程、异常捕获点以及重要的操作步骤中，应使用 Python 的 `logging`或 loguru 进行日志记录，确保日志内容清晰、结构化，并包含必要的上下文信息（如用户ID、请求ID等），以便于后续的调试和问题排查。
    - 日志级别应合理使用，如 `DEBUG` 用于开发调试，`INFO` 用于正常操作记录，`WARNING` 用于潜在问题，`ERROR` 用于错误事件，`CRITICAL` 用于严重错误。
    - 日志记录应使用英文，保持国际化和专业性，并且日志消息应简洁明了，能够清晰地传达事件的发生和相关信息。


## 5. 注释与文档 (Comments & Documentation)
- **注释和文档应使用英文**，以保持国际化和专业性。
- **Docstrings**：核心公共函数、类、复杂的业务方法必须包含文档字符串，说明其功能、参数详情和返回类型。
- **内联注释**：对于反直觉的代码实现或特别复杂的逻辑，需要有注释说明“为什么”这么写，而不仅仅是“做了什么”。


在每一次开发或答疑中，请将这份开发规范作为判断代码质量和架构是否合理的评价标准。
