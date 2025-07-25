﻿# cotton_toolkit/config/loader.py

import os
import re

import yaml
import logging  # Ensure logging is imported
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

from pydantic import ValidationError

# 确保从 models.py 正确导入 MainConfig 和 GenomeSourcesConfig, GenomeSourceItem
from cotton_toolkit.config.models import MainConfig, GenomeSourcesConfig, GenomeSourceItem  # ADD GenomeSourceItem

# --- 模块级缓存变量 ---
_GENOME_SOURCES_CACHE: Optional[Dict[str, GenomeSourceItem]] = None  # 缓存的类型改为 Dict[str, GenomeSourceItem]
_LAST_CACHED_GS_FILE_PATH: Optional[str] = None


# --- 国际化和日志设置 ---
# 假设 _ 函数已由主应用程序入口设置到 builtins
# 为了让静态检查工具识别 _，可以这样做：
try:
    import builtins

    _ = builtins._  # type: ignore
except (AttributeError, ImportError):  # builtins._ 未设置或导入builtins失败
    # 如果在测试或独立运行此模块时，_ 可能未设置
    def _(text: str) -> str:
        return text

logger = logging.getLogger("cotton_toolkit.loader")

# --- 获取本地已下载文件的预期路径 ---
def get_local_downloaded_file_path(config: MainConfig, genome_info: GenomeSourceItem, file_key: str) -> Optional[str]:
    """
    获取某个基因组的特定类型文件的本地期望路径。
    此版本会正确地包含基因组版本的子目录。
    """
    if not hasattr(genome_info, f"{file_key}_url"):
        return None

    url = getattr(genome_info, f"{file_key}_url")
    if not url:
        return None

    filename = os.path.basename(url)
    base_dir = config.downloader.download_output_base_dir

    # 确保 genome_info 有 version_id 属性，如果没有则尝试从 species_name 推断或使用默认值
    version_identifier = getattr(genome_info, 'version_id', None)
    if not version_identifier:
        # 如果没有version_id，退回到使用 species_name 或一个通用名称
        version_identifier = re.sub(r'[\\/*?:"<>|]', "_", genome_info.species_name).replace(" ", "_") if genome_info.species_name else "unknown_genome"

    version_specific_dir = os.path.join(base_dir, version_identifier)

    return os.path.join(version_specific_dir, filename)


def save_config(config: MainConfig, path: str) -> bool:
    """将配置对象保存到YAML文件。"""
    try:
        # 更新 exclude 参数中的字段名
        config_dict = config.model_dump(exclude={'config_file_abs_path_'}, exclude_none=True, exclude_defaults=False)

        with open(path, 'w', encoding='utf-8') as f:
            yaml.dump(config_dict, f, allow_unicode=True, sort_keys=False, indent=2)
        logger.info(_("配置文件已成功保存到: {}").format(path))
        return True
    except Exception as e:
        logger.error(_("保存配置文件到 '{}' 时发生错误: {}").format(path, e))
        return False


def load_config(path: str) -> MainConfig:
    """从指定路径加载主配置文件并进行验证。"""
    abs_path = os.path.abspath(path)
    info = _("正在从 '{}' 加载主配置文件...")
    logger.info(info.format(abs_path))
    try:
        with open(abs_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)

        config_obj = MainConfig.model_validate(data)

        # 更新设置字段的名称
        setattr(config_obj, 'config_file_abs_path_', abs_path) # 更新设置字段的名称

        logger.info(_("主配置文件加载并验证成功。"))
        return config_obj
    except FileNotFoundError:
        logger.error(_("配置文件未找到: {}").format(abs_path))
        raise
    except yaml.YAMLError as e:
        logger.error(_("解析YAML文件时发生错误 '{}': {}").format(abs_path, e))
        raise
    except ValidationError as e:  # Pydantic 的 ValidationError 会捕获所有验证失败
        logger.error(_("配置文件验证失败 '{}':\n{}").format(abs_path, e))
        raise
    except Exception as e:
        logger.error(_("加载配置文件时发生未知错误 '{}': {}").format(abs_path, e))
        raise


def get_genome_data_sources(config: MainConfig, logger_func=None) -> Dict[str, GenomeSourceItem]:
    """从主配置中指定的基因组源文件加载数据。"""
    # config 现在是 MainConfig 实例，访问 config.downloader 是安全的
    if not config.downloader.genome_sources_file:
        if logger_func: logger_func(_("警告: 配置文件中未指定基因组源文件。"), "WARNING")
        return {}

    config_dir = os.path.dirname(getattr(config, 'config_file_abs_path_', '.')) # 更新访问字段的名称
    sources_path = os.path.join(config_dir, config.downloader.genome_sources_file)

    if not os.path.exists(sources_path):
        if logger_func: logger_func(_("警告: 基因组源文件未找到: '{}'").format(sources_path), "WARNING")
        return {}

    try:
        with open(sources_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)

        # 使用 GenomeSourcesConfig (Pydantic BaseModel) 来验证和加载数据
        # 这会自动将嵌套的字典 item_data 转换为 GenomeSourceItem 实例
        genome_sources_config = GenomeSourcesConfig.model_validate(data)

        genome_sources_dict = {}
        for version_id, item_data in genome_sources_config.genome_sources.items():
            # Pydantic 已经处理了嵌套的验证和类型转换，item_data 已经是 GenomeSourceItem 实例
            # 在这里，如果 GenomeSourceItem 没有 version_id 属性，可以手动添加
            # 例如：setattr(item_data, 'version_id', version_id)
            # 或者在 GenomeSourceItem 定义中添加 version_id: str = None (如果 config.yml 中没有)
            # 根据您提供的 models.py，GenomeSourceItem 没有 version_id 属性。
            # 这里需要确保将其添加，以便 get_local_downloaded_file_path 可以使用它
            setattr(item_data, 'version_id', version_id)  # 补充 version_id

            genome_sources_dict[version_id] = item_data

        if logger_func: logger_func(_("已成功加载 {} 个基因组源。").format(len(genome_sources_dict)))
        return genome_sources_dict
    except ValidationError as e:  # 捕获 Pydantic 验证错误
        if logger_func: logger_func(_("加载基因组源文件时验证出错 '{}':\n{}").format(sources_path, e), "ERROR")
        return {}
    except Exception as e:
        if logger_func: logger_func(_("加载基因组源文件时发生错误 '%s': %s"), sources_path, e)
        return {}


def generate_default_config_files(output_dir: str, overwrite: bool = False, main_config_filename="config.yml",
                                  sources_filename="genome_sources_list.yml") -> Tuple[
    bool, Optional[str], Optional[str]]:
    """生成默认的配置文件和基因组源列表文件。"""
    try:
        os.makedirs(output_dir, exist_ok=True)
        main_config_path = os.path.join(output_dir, main_config_filename)
        sources_path = os.path.join(output_dir, sources_filename)

        if not overwrite and (os.path.exists(main_config_path) or os.path.exists(sources_path)):
            logger.warning(_("一个或多个默认配置文件已存在且不允许覆盖。操作已取消。"))
            return False, None, None

        # 创建并保存默认主配置 (MainConfig 现在是 Pydantic BaseModel)
        default_config = MainConfig()
        default_config.downloader.genome_sources_file = sources_filename  # 指向相对路径
        save_config(default_config, main_config_path)

        # 创建并保存默认基因组源文件 (GenomeSourcesConfig 现在是 Pydantic BaseModel)
        default_sources_data = GenomeSourcesConfig()

        with open(sources_path, 'w', encoding='utf-8') as f:
            yaml.dump(default_sources_data.model_dump(exclude_none=True), f, allow_unicode=True, sort_keys=False,
                      indent=2)

        return True, main_config_path, sources_path

    except Exception as e:
        logger.error(_("生成默认配置文件时发生错误: {}").format(e), exc_info=True)
        return False, None, None



def check_annotation_file_status(config: MainConfig, genome_info: GenomeSourceItem, file_type: str) -> str:
    # 此函数逻辑不变，因为它已经期望 MainConfig 和 GenomeSourceItem 是正确类型的对象
    local_path = get_local_downloaded_file_path(config, genome_info, file_type)

    if not local_path:
        return "not_applicable"

    if os.path.exists(local_path):
        if os.path.getsize(local_path) > 0:
            return 'complete'
        else:
            return 'incomplete'
    else:
        return 'missing'