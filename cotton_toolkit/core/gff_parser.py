﻿# cotton_toolkit/core/gff_parser.py
import gzip
import logging
import os
import re
from typing import Dict, Any, Optional, Callable, List, Tuple, Iterator, Union

import gffutils
import pandas as pd
from diskcache import Cache

# 国际化函数占位符
try:
    import builtins

    _ = builtins._
except (AttributeError, ImportError):
    def _(text: str) -> str:
        return text

logger = logging.getLogger("cotton_toolkit.gff_parser")


def _find_full_seqid(db: gffutils.FeatureDB, chrom_part: str, log: Callable) -> Optional[str]:
    """
    使用正则表达式在数据库中查找完整的序列ID (seqid)。
    """
    all_seqids = list(db.seqids())
    log(f"数据库中所有可用的序列ID: {all_seqids[:10]}...", "DEBUG")

    for seqid in all_seqids:
        if seqid.lower() == chrom_part.lower():
            log(_("精确匹配成功: '{}' -> '{}'").format(chrom_part, seqid), "INFO")
            return seqid

    pattern = re.compile(f".*[^a-zA-Z0-9]{re.escape(chrom_part)}$|^{re.escape(chrom_part)}$", re.IGNORECASE)
    matches = [seqid for seqid in all_seqids if pattern.match(seqid)]

    if len(matches) == 1:
        log(_("模糊匹配成功: '{}' -> '{}'").format(chrom_part, matches[0]), "INFO")
        return matches[0]

    if len(matches) > 1:
        log(_("警告: 发现多个可能的匹配项 for '{}': {}。将使用第一个: {}").format(chrom_part, matches, matches[0]),
            "WARNING")
        return matches[0]

    log(_("错误: 无法在数据库中找到与 '{}' 匹配的序列ID。").format(chrom_part), "ERROR")
    return None


def _gff_gene_filter(gff_filepath: str) -> Iterator[Union[gffutils.feature.Feature, str]]:
    """
    一个生成器函数，用于逐行读取GFF文件并仅产出'gene'类型的特征。
    """
    is_gzipped = gff_filepath.endswith('.gz')
    opener = gzip.open if is_gzipped else open
    mode = 'rt' if is_gzipped else 'r'

    logger.debug(_("Opening {}{}file for parsing: {}").format('gzipped ' if is_gzipped else '', '', gff_filepath))

    with opener(gff_filepath, mode, encoding='utf-8', errors='ignore') as gff_file:
        for line in gff_file:
            if line.startswith('#'):
                continue
            columns = line.strip().split('\t')
            if len(columns) > 2 and columns[2] == 'gene':
                try:
                    feature_obj = gffutils.feature.feature_from_line(line)
                    yield feature_obj
                except Exception as e:
                    logger.warning(_("Skipping malformed GFF line: {} | Error: {}").format(line.strip(), e))

def create_gff_database(
        gff_filepath: str,
        db_path: str,
        force: bool = False,
        status_callback: Optional[Callable[[str, str], None]] = None,
        id_regex: Optional[str] = None
):
    """
    从 GFF3 文件创建 gffutils 数据库，并使用正则表达式规范化ID。
    """
    log = status_callback if status_callback else lambda msg, level: print(f"[{level}] {msg}")

    if os.path.exists(db_path) and os.path.getsize(db_path) > 0 and not force:
        log(_("数据库 '{}' 已存在且有效，直接使用。").format(os.path.basename(db_path)), "DEBUG")
        return db_path

    db_dir = os.path.dirname(db_path)
    if not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)

    log(_("正在创建GFF数据库(仅包含基因)：{} 从 {}").format(os.path.basename(db_path), os.path.basename(gff_filepath)),
        "INFO")

    try:
        def id_spec_func(feature):
            original_id = feature.attributes.get('ID', [None])[0]
            if not original_id:
                return None
            return _apply_regex_to_id(original_id, id_regex) if id_regex else original_id

        gene_iterator = _gff_gene_filter(gff_filepath)

        gffutils.create_db(
            gene_iterator,
            dbfn=db_path,
            force=force,
            id_spec=id_spec_func,
            keep_order=True,
            merge_strategy="merge",
            sort_attribute_values=True,
            disable_infer_transcripts=True,
            disable_infer_genes=True,
        )
        log(_("成功创建GFF数据库: {}").format(os.path.basename(db_path)), "INFO")
        return db_path

    except Exception as e:
        log(_("错误: 创建GFF数据库 '{}' 失败: {}").format(os.path.basename(db_path), e), "ERROR")
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except OSError:
                pass
        raise


def extract_gene_details(feature: gffutils.Feature) -> Dict[str, Any]:
    """从 gffutils.Feature 对象中提取关键基因信息。"""
    attributes = dict(feature.attributes)
    return {
        'gene_id': feature.id,
        'chrom': feature.chrom,
        'start': feature.start,
        'end': feature.end,
        'strand': feature.strand,
        'source': feature.source,
        'feature_type': feature.featuretype,
        'aliases': attributes.get('Alias', ['N/A'])[0],
        'description': attributes.get('description', ['N/A'])[0]
    }


def _apply_regex_to_id(gene_id: str, regex_pattern: Optional[str]) -> str:
    """
    使用正则表达式从一个字符串中提取基因ID，并清除首尾空白。
    """
    processed_id = str(gene_id).strip()
    if not regex_pattern:
        return processed_id
    match = re.search(regex_pattern, processed_id)
    return match.group(1) if match and match.groups() else processed_id


def get_genes_in_region(
        assembly_id: str,
        gff_filepath: str,
        db_storage_dir: str,
        region: Tuple[str, int, int],
        force_db_creation: bool = False,
        status_callback: Optional[Callable[[str, str], None]] = None,
        gene_id_regex: Optional[str] = None,
        progress_callback: Optional[Callable[[int, str], None]] = None
) -> List[Dict[str, Any]]:
    """
    从GFF文件中查找位于特定染色体区域内的所有基因，并报告进度。
    """
    log = status_callback if status_callback else lambda msg, level: print(f"[{level}] {msg}")
    progress = progress_callback if progress_callback else lambda p, m: None

    db_path = os.path.join(db_storage_dir, f"{assembly_id}_genes.db")
    user_chrom_part, start, end = region

    try:
        progress(10, _("正在准备GFF数据库..."))
        created_db_path = create_gff_database(gff_filepath, db_path, force_db_creation, status_callback,
                                              id_regex=gene_id_regex)
        if not created_db_path:
            raise RuntimeError(_("无法获取或创建GFF数据库，无法查询区域基因。"))

        progress(40, _("正在打开数据库并查找序列ID..."))
        db = gffutils.FeatureDB(created_db_path, keep_order=True)
        full_seqid = _find_full_seqid(db, user_chrom_part, log)

        if not full_seqid:
            progress(100, _("在数据库中未找到匹配的染色体/序列。"))
            return []

        progress(60, _("正在查询区域: {}...").format(f"{full_seqid}:{start}-{end}"))
        genes_in_region = list(db.region(region=(full_seqid, start, end), featuretype='gene'))

        progress(80, _("正在提取基因详细信息..."))
        results = [extract_gene_details(gene) for gene in genes_in_region]
        log(_("在区域内共找到 {} 个基因。").format(len(results)), "INFO")
        progress(100, _("区域基因提取完成。"))
        return results

    except Exception as e:
        log(_("查询GFF区域时发生错误: {}").format(e), "ERROR")
        logger.exception(_("GFF区域查询失败的完整堆栈跟踪:"))
        progress(100, _("查询时发生错误。"))
        return []


def get_gene_info_by_ids(
        assembly_id: str,
        gff_filepath: str,
        db_storage_dir: str,
        gene_ids: List[str],
        force_db_creation: bool = False,
        status_callback: Optional[Callable[[str, str], None]] = None,
        gene_id_regex: Optional[str] = None,
        progress_callback: Optional[Callable[[int, str], None]] = None
) -> pd.DataFrame:
    """
    根据基因ID列表，从GFF数据库中批量查询基因信息，并报告进度。
    """
    log = status_callback if status_callback else lambda msg, level: print(f"[{level}] {msg}")
    progress = progress_callback if progress_callback else lambda p, m: None
    db_path = os.path.join(db_storage_dir, f"{assembly_id}_genes.db")
    try:
        progress(10, _("正在准备GFF数据库..."))
        created_db_path = create_gff_database(gff_filepath, db_path, force_db_creation, status_callback,
                                              id_regex=gene_id_regex)
        if not created_db_path:
            raise RuntimeError(_("无法获取或创建GFF数据库，无法查询基因ID。"))

        progress(40, _("正在打开数据库..."))
        db = gffutils.FeatureDB(created_db_path, keep_order=True)

        log(_("正在根据 {} 个ID查询基因信息...").format(len(gene_ids)), "INFO")
        found_genes = []
        not_found_ids = []
        total_ids = len(gene_ids)

        for i, gene_id in enumerate(gene_ids):
            # 在循环内部报告进度
            if i % 100 == 0 or i == total_ids - 1:  # 每处理100个或最后一个时更新进度
                percentage = 40 + int(((i + 1) / total_ids) * 55)  # 进度从40%到95%
                progress(percentage, f"{_('正在查询基因')} {i + 1}/{total_ids}")

            try:
                gene_feature = db[gene_id]
                found_genes.append(extract_gene_details(gene_feature))
            except gffutils.exceptions.FeatureNotFoundError:
                not_found_ids.append(gene_id)

        if not_found_ids:
            log(_("警告: {} 个基因ID未在GFF数据库中找到: {}{}").format(len(not_found_ids), ', '.join(not_found_ids[:5]),
                                                                       '...' if len(not_found_ids) > 5 else ''),
                "WARNING")

        if not found_genes:
            progress(100, _("查询完成，未找到任何基因。"))
            return pd.DataFrame()

        result_df = pd.DataFrame(found_genes)
        log(_("成功查询到 {} 个基因的详细信息。").format(len(found_genes)), "INFO")
        progress(100, _("基因查询完成。"))
        return result_df

    except Exception as e:
        log(_("根据ID查询GFF时发生错误: {}").format(e), "ERROR")
        logger.exception(_("GFF ID查询失败的完整堆栈跟踪:"))
        progress(100, _("查询时发生错误。"))
        return pd.DataFrame()