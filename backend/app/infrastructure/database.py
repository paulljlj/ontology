#这段代码是数据库会话管理工具，负责连接数据库、创建会话、自动开关。 

from contextlib import contextmanager
# 导入上下文管理器装饰器，用来实现安全、自动释放资源的数据库会话作用域

from sqlalchemy import create_engine
# create_engine：创建SQLAlchemy数据库引擎（数据库连接核心）
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
# DeclarativeBase：ORM所有数据表模型的基础父类
# Session：数据库会话，用来执行增删改查
# sessionmaker：会话工厂，批量生成数据库会话对象

from app.infrastructure.config import settings
# 导入项目配置，settings.database_url存放数据库连接地址

# 继承 SQLAlchemy 2.0 提供的声明式基类 DeclarativeBase。
# 所有数据库模型类（User、Order 等）都要继承 Base。
class Base(DeclarativeBase):
    pass #空类，不需要额外代码；DeclarativeBase 内部自动实现元数据管理、表映射逻辑。


engine = create_engine(settings.database_url, pool_pre_ping=True) 
# engine 只管连接管理，不负责事务、CRUD；真正操作数据库靠 Session。
# create_engine()：SQLAlchemy 创建数据库引擎，是底层数据库连接核心对象。
# settings.database_url：数据库连接地址字符
# pool_pre_ping=True
# 连接池预检测。每次从连接池取出连接前，先发一条测试 SQL 验证连接是否有效。
# 解决长时间空闲导致数据库断开、抛出连接失效异常问题。
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
# sessionmaker()：工厂函数，用来生成数据库会话 Session
# bind=engine：会话绑定到上面创建的数据库引擎，会话通过 engine 建立连接
# autoflush=False
# 自动刷新关闭。
# True：每次查询前自动把 pending 变更刷到数据库；False 需要手动 flush/commit，业务更可控，避免隐形 SQL。
# autocommit=False
# 关闭自动提交。所有增删改操作必须手动调用 session.commit() 才持久化到数据库。
# SessionLocal 只是会话工厂模板，不是会话实例；调用 SessionLocal() 才得到一个 session。


def get_session():
    """
    FastAPI 依赖注入专用数据库会话生成器
    使用with上下文自动关闭session,无自动事务处理,需要手动commit/rollback
    """
    with SessionLocal() as session:  # 创建数据库会话，with退出时自动执行session.close()归还连接
        yield session                # 产出session对象提供给路由函数使用，函数在此暂停


@contextmanager
def session_scope():
    """
    自定义事务上下文管理器，适用于脚本、后台任务
    正常执行自动commit:出现异常自动rollback:最终必定关闭会话释放连接
    使用方式:with session_scope() as sess:
    """
    # 实例化数据库会话
    session = SessionLocal()
    try:
        yield session       # 将session交给with内部业务代码执行CRUD，函数暂停在此处
        session.commit()    # with内部代码无异常执行完毕，自动提交事务
    except Exception:
        session.rollback()  # 捕获任意异常，事务回滚，撤销所有未提交修改
        raise               # 重新抛出异常，不吞噬错误，供上层捕获处理
    finally:
        # 无论正常结束还是异常，一定会执行，关闭会话，归还数据库连接
        session.close()
