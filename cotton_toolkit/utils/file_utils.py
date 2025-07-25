﻿# cotton_toolkit/utils/file_utils.py
import io
import os
import pandas as pd
import gzip
import logging
from typing import Callable, Optional

from cotton_toolkit.core.file_normalizer import normalize_to_csv

try:
    import builtins
    _ = builtins._
except (AttributeError, ImportError):
    def _(text: str) -> str:
        return text


logger = logging.getLogger(__name__)


def prepare_input_file(
        original_path: str,
        status_callback: Callable[[str, str], None],
        temp_dir: str
) -> Optional[str]:
    """
    【通用版】预处理一个输入文件，确保其为标准的CSV格式，并使用缓存。
    支持 .csv, .txt, .xlsx 及其 .gz 压缩版本。

    :param original_path: 原始文件路径
    :param status_callback: 日志回调函数 (msg, level)
    :param temp_dir: 用于存放缓存/转换后文件的目录
    :return: 标准化后的CSV文件路径，如果失败则返回None
    """
    if not os.path.exists(original_path):
        status_callback(_("ERROR: 输入文件不存在: {}").format(original_path), "ERROR")
        return None

    os.makedirs(temp_dir, exist_ok=True)

    base_name = os.path.basename(original_path)
    # 标准化缓存文件名，去除所有原始扩展名
    cache_base_name = base_name.split('.')[0]
    cached_csv_path = os.path.join(temp_dir, f"{cache_base_name}_standardized.csv")

    # --- 缓存检查：如果原始文件未变，直接使用缓存 ---
    if os.path.exists(cached_csv_path):
        try:
            original_mtime = os.path.getmtime(original_path)
            cached_mtime = os.path.getmtime(cached_csv_path)
            if cached_mtime >= original_mtime:
                status_callback(_("发现有效的缓存文件，将直接使用: {}").format(os.path.basename(cached_csv_path)),
                                "INFO")
                return cached_csv_path

        except OSError as e:
            status_callback(_("无法检查文件时间戳: {}").format(e), "WARNING")

    status_callback(_("正在处理新文件或已更新的文件: {}").format(base_name), "INFO")

    # --- 调用核心规范器进行转换 ---
    try:
        # 这里直接调用我们刚刚创建的强大函数
        result_path = normalize_to_csv(original_path, cached_csv_path)
        if result_path:
            status_callback(_("文件已成功转换为标准CSV并缓存: {}").format(os.path.basename(cached_csv_path)), "INFO")
            return result_path

        else:
            status_callback(_("文件规范化失败: {}").format(base_name), "ERROR")
            return None
    except Exception as e:
        status_callback(_("处理文件 {} 时发生严重错误: {}").format(base_name, e), "ERROR")
        return None


def smart_load_file(file_path: str, logger_func: Optional[Callable] = None) -> Optional[pd.DataFrame]:
    """
    智能加载数据文件，能自动处理 .gz 压缩和多种表格格式 (Excel, CSV, TSV)。

    Args:
        file_path (str): 要加载的文件路径。
        logger_func (Callable, optional): 用于记录日志的回调函数。如果为None，则使用标准日志。

    Returns:
        Optional[pd.DataFrame]: 成功则返回一个DataFrame，失败则返回None。
    """
    # 如果没有提供日志函数，则使用一个默认的，避免程序出错
    if logger_func is None:
        logger_func = logging.info

    # 1. 检查文件是否存在
    if not file_path or not os.path.exists(file_path):
        logger_func(_("错误: 文件不存在 -> {}").format(file_path), "ERROR")
        return None

    file_name_for_log = os.path.basename(file_path)

    try:
        # 2. 自动处理 .gz 压缩
        is_gzipped = file_path.lower().endswith('.gz')
        open_func = gzip.open if is_gzipped else open

        # 获取用于判断文件类型的扩展名（去除.gz）
        uncompressed_path = file_path.lower().replace('.gz', '') if is_gzipped else file_path.lower()
        file_ext = os.path.splitext(uncompressed_path)[1]

        logger_func(_("正在读取文件: {} (类型: {}, 压缩: {})").format(file_name_for_log, file_ext, is_gzipped), "DEBUG")

        with open_func(file_path, 'rb') as f:
            content_bytes = f.read()

        # 3. 根据文件扩展名选择合适的读取方式
        df = None
        if file_ext in ['.xlsx', '.xls']:
            # 读取 Excel 文件
            df = pd.read_excel(io.BytesIO(content_bytes), engine='openpyxl')

        elif file_ext in ['.csv', '.tsv', '.txt']:
            # 读取文本文件 (CSV, TSV等)
            # 先尝试用 utf-8 解码
            try:
                content_str = content_bytes.decode('utf-8')
            except UnicodeDecodeError:
                logger_func(_("文件 {} 使用UTF-8解码失败，尝试latin-1编码。").format(file_name_for_log), "WARNING")
                content_str = content_bytes.decode('latin-1', errors='ignore')

            # 自动检测分隔符 (制表符优先)
            first_line = content_str.splitlines()[0] if content_str else ""
            if '\t' in first_line:
                separator = '\t'
                logger_func(_("检测到制表符(Tab)分隔符: {}").format(file_name_for_log), "DEBUG")
            else:
                separator = ','
                logger_func(_("默认使用逗号(Comma)分隔符: {}").format(file_name_for_log), "DEBUG")

            df = pd.read_csv(io.StringIO(content_str), sep=separator, engine='python')

        else:
            logger_func(_("警告: 不支持的文件扩展名 '{}' 来自文件: {}").format(file_ext, file_name_for_log), "WARNING")
            return None

        logger_func(_("文件 {} 加载成功，共 {} 行。").format(file_name_for_log, len(df)), "INFO")
        return df

    except Exception as e:
        logger_func(_("加载或解析文件 {} 时发生严重错误: {}").format(file_name_for_log, e), "ERROR")
        return None



def save_dataframe_as(df: pd.DataFrame, output_path: str, logger_func: Optional[Callable] = None) -> bool:
    """
    根据输出路径的扩展名，将DataFrame保存为CSV或Excel文件。

    Args:
        df (pd.DataFrame): 需要保存的DataFrame。
        output_path (str): 输出文件的完整路径，应以 .csv 或 .xlsx 结尾。
        logger_func (Callable, optional): 用于记录日志的回调函数。

    Returns:
        bool: 保存成功则返回 True，否则返回 False。
    """
    if logger_func is None:
        # 如果没有提供日志函数，则使用简单的 print
        logger_func = lambda msg, level="INFO": print(f"[{level}] {msg}")

    # 确保输出目录存在
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    # 获取小写的文件扩展名
    file_ext = os.path.splitext(output_path)[1].lower()

    try:
        if file_ext == '.csv':
            # 使用 utf-8-sig 编码以确保Excel能正确打开包含中文的CSV
            df.to_csv(output_path, index=False, encoding='utf-8-sig')
            logger_func(_("DataFrame 已成功保存为CSV文件: {}").format(output_path), "INFO")
        elif file_ext == '.xlsx':
            df.to_excel(output_path, index=False, engine='openpyxl')
            logger_func(_("DataFrame 已成功保存为Excel文件: {}").format(output_path), "INFO")
        else:
            logger_func(_("错误: 不支持的文件格式 '{}'。请使用 '.csv' 或 '.xlsx'。").format(file_ext), "ERROR")
            return False

        return True
    except Exception as e:
        logger_func(_("保存DataFrame到 {} 时发生错误: {}").format(output_path, e), "ERROR")
        return False

