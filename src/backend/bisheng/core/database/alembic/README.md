Generic single-database configuration.

* 创建迁移脚本
    ```bash
    alembic revision -m "描述信息"
    ```
* 自动生成迁移脚本，基于模型和数据库的差异，差异较大时建议先手动创建迁移脚本再修改
    ```bash
    alembic revision --autogenerate -m "描述信息"
    ```
* 应用所有未应用的迁移脚本
    ```bash
    alembic upgrade head
    ```

* 应用到指定版本
    ```bash
    alembic upgrade <版本号>
    ```

* 回滚到上一个版本
    ```bash
    alembic downgrade -1
    ```

* 回滚到指定版本
    ```bash
    alembic downgrade <版本号>
    ```


* 查看当前数据库版本
    ```bash
    alembic current
    ```

* 查看迁移历史
    ```bash
    alembic history
    ```

* 查看未应用的迁移脚本
    ```bash
    alembic heads
    ```

* 生成迁移脚本的SQL文件，而不是直接应用到数据库
    ```bash
    alembic upgrade head --sql > upgrade.sql
    ```

* 配置文件及目录说明
    * alembic.ini: 主配置文件，包含数据库连接字符串等全局配置
    * bisheng/core/database/alembic/env.py: 环境配置文件，定义了如何连接数据库和加载模型
    * bisheng/core/database/alembic/versions/: 存放迁移脚本的目录
    * bisheng/core/database/alembic/script.py.mako: 迁移脚本模板文件
    * bisheng/core/database/alembic/README.md: 本说明文件