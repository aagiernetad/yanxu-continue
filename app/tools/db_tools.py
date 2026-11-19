"""MySQL 只读查询工具。查询校验用于收紧输入，数据库权限和只读事务作为实际边界。"""
import csv
import io
import logging
import os
import re
from contextlib import contextmanager

from dotenv import load_dotenv
from langchain_core.tools import tool
from mysql.connector import Error, connect

from app.api.monitor import monitor

load_dotenv()
MAX_ROWS = 200
MAX_RESULT_CHARS = 30000


def get_db_config():
    config = {
        "host": os.getenv("MYSQL_HOST", "localhost"),
        "port": int(os.getenv("MYSQL_PORT", "3306")),
        "user": os.getenv("MYSQL_USER"), "password": os.getenv("MYSQL_PASSWORD"),
        "database": os.getenv("MYSQL_DATABASE"),
        "charset": os.getenv("MYSQL_CHARSET", "utf8mb4"),
        "collation": os.getenv("MYSQL_COLLATION", "utf8mb4_unicode_ci"),
        "sql_mode": os.getenv("MYSQL_SQL_MODE", "TRADITIONAL"),
        "autocommit": False, "connection_timeout": 10, "read_timeout": 10, "write_timeout": 10,
    }
    if any(config[key] is None for key in ("user", "password", "database")):
        raise ValueError("缺失数据库配置：请配置 MYSQL_USER、MYSQL_PASSWORD、MYSQL_DATABASE")
    return config


@contextmanager
def readonly_cursor():
    with connect(**get_db_config()) as conn:
        with conn.cursor() as cursor:
            cursor.execute("SET SESSION MAX_EXECUTION_TIME=5000")
            cursor.execute(f"SET SESSION SQL_SELECT_LIMIT={MAX_ROWS + 1}")
            conn.start_transaction(readonly=True)
            try:
                yield cursor
            finally:
                conn.rollback()


def validate_readonly_query(query: str) -> str:
    """保守地只开放单条 SELECT；不以正则校验替代只读数据库账号。"""
    query = query.strip().removesuffix(";").strip()
    if not query or len(query) > 10000 or not re.match(r"(?i)^SELECT\b", query):
        raise ValueError("只允许单条 SELECT 查询（不支持 CTE、写操作或管理语句）")
    if any(marker in query for marker in (";", "--", "#", "/*", "*/", "@", "\x00")):
        raise ValueError("不允许多语句、注释或会话变量")
    if re.search(r"(?i)\b(INTO|OUTFILE|DUMPFILE|LOAD_FILE|SLEEP|BENCHMARK|GET_LOCK|RELEASE_LOCK|FOR|LOCK|PROCEDURE)\b", query):
        raise ValueError("查询包含不允许的文件、锁或副作用操作")
    for limit in re.findall(r"(?i)\bLIMIT\s+(\d+)(?:\s*,\s*(\d+))?", query):
        if int(limit[1] or limit[0]) > MAX_ROWS:
            raise ValueError(f"LIMIT 不能超过 {MAX_ROWS} 行")
    return query


def csv_result(cursor):
    rows = cursor.fetchmany(MAX_ROWS + 1)
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow([column[0] for column in cursor.description])
    writer.writerows(rows[:MAX_ROWS])
    result = output.getvalue()
    if len(rows) > MAX_ROWS:
        result += f"\n[结果已截断：最多返回 {MAX_ROWS} 行]"
    if len(result) > MAX_RESULT_CHARS:
        result = result[:MAX_RESULT_CHARS] + "\n[结果过长，已截断；请缩小查询范围]"
    return result


def query_error(exc):
    if isinstance(exc, ValueError):
        return f"查询被拒绝：{exc}"
    logging.exception("数据库查询失败")
    return "数据库查询失败，请检查只读账号权限、查询语法或服务端日志。"


@tool
def list_sql_tables() -> str:
    """列出当前数据库中的真实表名，供后续只读查询使用。"""
    monitor.report_tool("数据库表名查询工具：list_sql_tables", {})
    try:
        with readonly_cursor() as cursor:
            cursor.execute("SHOW TABLES")
            names = [row[0] for row in cursor.fetchall()]
            return "可用的表有：" + ", ".join(names) if names else "没有可用的表"
    except (Error, ValueError) as exc:
        return query_error(exc)


@tool
def get_table_data(table_name: str) -> str:
    """预览当前数据库中实际存在的表，最多返回 100 行 CSV。"""
    monitor.report_tool("数据库表数据查询工具：get_table_data", {"table_name": table_name})
    try:
        with readonly_cursor() as cursor:
            cursor.execute("SHOW TABLES")
            if table_name not in {row[0] for row in cursor.fetchall()}:
                raise ValueError("表名不在当前数据库表清单中")
            identifier = table_name.replace("`", "``")
            cursor.execute(f"SELECT * FROM `{identifier}` LIMIT 100")
            return csv_result(cursor)
    except (Error, ValueError) as exc:
        return query_error(exc)


@tool
def execute_sql_query(query: str) -> str:
    """执行单条只读 SELECT（最多 200 行）；先确认真实表名和字段，不支持写入或 CTE。"""
    monitor.report_tool("数据库表数据查询工具：execute_sql_query", {"query": query})
    try:
        query = validate_readonly_query(query)
        with readonly_cursor() as cursor:
            cursor.execute(query)
            return csv_result(cursor)
    except (Error, ValueError) as exc:
        return query_error(exc)
