import pandas as pd
import csv
from loguru import logger
import openpyxl
from typing import List
from uuid import uuid4
import os
import math
import chardet


# --- 辅助函数 ---
def unmerge_and_read_sheet(sheet_obj):
    """
    读取一个 openpyxl 工作表对象，通过将合并区域的左上角单元格的值
    传播到该范围内的所有单元格来取消合并，并以列表的列表形式返回数据。
    """
    if sheet_obj.max_row == 0 or sheet_obj.max_column == 0:
        return []
    data_grid = [
        [None for _ in range(sheet_obj.max_column)] for _ in range(sheet_obj.max_row)
    ]
    for r_idx, row in enumerate(sheet_obj.iter_rows()):
        for c_idx, cell in enumerate(row):
            data_grid[r_idx][c_idx] = cell.value

    merged_cell_ranges = list(sheet_obj.merged_cells.ranges)
    for merged_range in merged_cell_ranges:
        min_col, min_row, max_col, max_row = merged_range.bounds
        top_left_cell_value = sheet_obj.cell(row=min_row, column=min_col).value
        for r in range(min_row, max_row + 1):
            for c in range(min_col, max_col + 1):
                data_grid[r - 1][c - 1] = top_left_cell_value
    return data_grid


def generate_markdown_table_string(
    header_rows_list_of_lists,
    data_rows_list_of_lists,
    num_columns,
):
    """
    根据表头和数据行生成 Markdown 表格字符串。
    """
    md_lines = []

    # 首先，添加所有表头行 (根据逻辑，这里只会有1行或0行)
    for row_values in header_rows_list_of_lists:
        md_lines.append(
            "| "
            + " | ".join(str(v) if v is not None else "" for v in row_values)
            + " |"
        )

    # 如果存在表头行，则添加分隔符
    if header_rows_list_of_lists and num_columns > 0:
        md_lines.append("|" + "---|" * num_columns)

    # 最后，添加所有数据行
    for row_values in data_rows_list_of_lists:
        md_lines.append(
            "| "
            + " | ".join(str(v) if v is not None else "" for v in row_values)
            + " |"
        )
    return "\n".join(md_lines)


# --- 核心 DataFrame 到 Markdown 处理逻辑 (根据最终排序要求修正) ---
def process_dataframe_to_markdown_files(
    df, source_name, num_header_rows, rows_per_markdown, output_dir, append_header=True
):
    """
    将单个 DataFrame 处理成分页的 Markdown 文件。
    强制规则：分隔符在第二行。
    最终数据排序规则：[降级的表头行] -> [表头前的数据行] -> [表头后的数据行]。
    """
    if df.empty:
        logger.warning(f"  源 '{source_name}' 的数据DataFrame为空，跳过Markdown生成。")
        return

    num_columns = df.shape[1]
    header_rows_as_lists = []

    if append_header:
        header_start, header_end = num_header_rows[0], num_header_rows[1]

        if header_start >= len(df):
            logger.warning(
                f"警告：源 '{source_name}' 的表头起始行 ({header_start}) 超出总行数 ({len(df)})，将没有表头。"
            )
            header_rows_as_lists = []
            data_block_df = df
        else:
            # 1. 强制选择指定范围的第一行作为唯一的“表头”
            single_header_df = df.iloc[header_start : header_start + 1]
            header_rows_as_lists = single_header_df.values.tolist()

            # 2. 识别出所有需要成为“数据”的部分
            #    - 表头之前的部分
            rows_before_header = df.iloc[0:header_start]
            #    - 原表头范围中被“降级”为数据的部分
            other_header_rows_as_data = df.iloc[header_start + 1 : header_end]
            #    - 表头之后的部分
            rows_after_header = df.iloc[header_end:]

            # 3. 【关键修改】按照您描述的最新顺序合并成最终的数据块
            #    新顺序: [降级的表头行] -> [表头前的数据行] -> [表头后的数据行]
            data_block_df = pd.concat(
                [other_header_rows_as_data, rows_before_header, rows_after_header],
                ignore_index=True,
            )

    else:
        # 如果不附加表头，所有行都是数据。
        header_rows_as_lists = []
        data_block_df = df

    if data_block_df.empty:
        if header_rows_as_lists:
            logger.debug(
                f"  源 '{source_name}' 只有表头数据。正在生成仅包含表头的文件..."
            )
            markdown_content = generate_markdown_table_string(
                header_rows_as_lists, [], num_columns
            )
            file_name = f"{source_name}_header_only.md"
            file_path = os.path.join(output_dir, file_name)
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(markdown_content)
                logger.debug(f"  已保存表头文件：'{file_path}'")
            except Exception as e:
                logger.error(f"  保存文件 '{file_path}' 时出错: {e}")
        else:
            logger.debug(f"  源 '{source_name}' 没有数据可供处理，跳过。")
        return

    num_data_rows_total = len(data_block_df)
    num_files_to_create = (
        math.ceil(num_data_rows_total / rows_per_markdown)
        if rows_per_markdown > 0
        else 1
    )

    logger.debug(
        f"  源 '{source_name}': 表头行数: {len(header_rows_as_lists)}, 总数据行数: {num_data_rows_total}, 每文件数据行: {rows_per_markdown}"
    )
    logger.debug(
        f"  将为源 '{source_name}' 创建 {num_files_to_create} 个Markdown文件。"
    )

    for i in range(num_files_to_create):
        start_idx = i * rows_per_markdown
        end_idx = min(start_idx + rows_per_markdown, num_data_rows_total)
        current_data_chunk_df = data_block_df.iloc[start_idx:end_idx]
        current_data_chunk_as_lists = current_data_chunk_df.values.tolist()

        markdown_content = generate_markdown_table_string(
            header_rows_as_lists, current_data_chunk_as_lists, num_columns
        )
        part_name = f"part_{i + 1}" if num_files_to_create > 1 else "full"
        file_name = f"{source_name}_{part_name}.md"
        file_path = os.path.join(output_dir, file_name)

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(markdown_content)
            logger.debug(
                f"  已保存：'{file_path}' (含 {len(current_data_chunk_df)} 行数据)"
            )
        except Exception as e:
            logger.error(f"  保存文件 '{file_path}' 时出错: {e}")


# --- Excel 特定处理 ---
def excel_file_to_markdown(
    excel_path, num_header_rows, rows_per_markdown, output_dir, append_header=True
):
    logger.debug(f"\n开始处理Excel文件：'{excel_path}'")
    try:
        workbook = openpyxl.load_workbook(excel_path, data_only=True, read_only=False)
    except Exception as e:
        logger.error(f"错误：无法加载Excel文件 '{excel_path}'。原因: {e}")
        return

    for sheet_name in workbook.sheetnames:
        logger.debug(f"\n  正在处理Excel工作表：'{sheet_name}'...")
        sheet_obj = workbook[sheet_name]

        unmerged_data_list_of_lists = unmerge_and_read_sheet(sheet_obj)

        if not unmerged_data_list_of_lists:
            logger.warning(f"  工作表 '{sheet_name}' 为空或读取失败，跳过。")
            continue

        df = pd.DataFrame(unmerged_data_list_of_lists)
        df.fillna("", inplace=True)

        if df.empty:
            logger.warning(f"  工作表 '{sheet_name}' 处理后为空DataFrame，跳过。")
            continue

        process_dataframe_to_markdown_files(
            df,
            sheet_name,
            num_header_rows,
            rows_per_markdown,
            output_dir,
            append_header=append_header,
        )
    if workbook:
        workbook.close()
    logger.debug(f"\nExcel文件 '{excel_path}' 处理完成。")


def get_file_encoding(file_path, default_encoding="utf-8"):
    """
    通过读取文件内容的样本来检测文件编码。
    """
    with open(file_path, "rb") as file:
        raw_data = file.read(2048)
        result = chardet.detect(raw_data)
        encoding = result["encoding"]
        return encoding if encoding else default_encoding


def detect_csv_delimiter(file_path, csv_encoding, sample_size=2048):
    """
    检测CSV文件的分隔符。
    """
    with open(file_path, "r", encoding=csv_encoding) as file:
        sample = file.read(sample_size)
        sniffer = csv.Sniffer()
        try:
            return sniffer.sniff(sample).delimiter
        except csv.Error:
            logger.warning(f"无法自动检测 '{file_path}' 的分隔符，将默认使用 ','。")
            return ","


# --- CSV 特定处理 ---
def csv_file_to_markdown(
    csv_path,
    num_header_rows,
    rows_per_markdown,
    output_dir,
    csv_encoding="utf-8",
    csv_delimiter=",",
    append_header=True,
):
    logger.debug(f"\n开始处理CSV文件：'{csv_path}'")
    try:
        detected_encoding = get_file_encoding(file_path=csv_path)
        logger.debug(f"检测到CSV文件 '{csv_path}' 的编码为: {detected_encoding}")
        detected_delimiter = detect_csv_delimiter(csv_path, detected_encoding)
        logger.debug(f"检测到CSV文件 '{csv_path}' 的分隔符为: '{detected_delimiter}'")

        df = pd.read_csv(
            csv_path,
            header=None,
            dtype=str,
            encoding=detected_encoding,
            sep=detected_delimiter,
            keep_default_na=False,
            engine="python",
        )
        df.fillna("", inplace=True)

    except pd.errors.EmptyDataError:
        logger.error(f"错误：CSV文件 '{csv_path}' 为空。")
        return
    except FileNotFoundError:
        logger.error(f"错误：CSV文件 '{csv_path}' 未找到。")
        return
    except Exception as e:
        logger.error(f"错误：无法读取CSV文件 '{csv_path}'。原因: {e}")
        return

    if df.empty:
        logger.warning(f"CSV文件 '{csv_path}' 为空或处理后为空，跳过。")
        return

    csv_filename_base = os.path.splitext(os.path.basename(csv_path))[0]

    process_dataframe_to_markdown_files(
        df,
        csv_filename_base,
        num_header_rows,
        rows_per_markdown,
        output_dir,
        append_header,
    )
    logger.debug(f"\nCSV文件 '{csv_path}' 处理完成。")


# --- 主调度函数 ---
def convert_file_to_markdown(
    input_file_path,
    num_header_rows,
    rows_per_markdown,
    base_output_dir="output_markdown_files",
    csv_encoding="utf-8",
    csv_delimiter=",",
    append_header=True,
):
    """
    将 Excel 或 CSV 文件转换为多个 Markdown 文件。
    """
    if not os.path.exists(input_file_path):
        logger.error(f"错误：输入文件 '{input_file_path}' 未找到。")
        return

    if not os.path.exists(base_output_dir):
        os.makedirs(base_output_dir)
        logger.debug(f"创建输出目录：'{base_output_dir}'")

    _, file_extension = os.path.splitext(input_file_path)
    file_extension = file_extension.lower()

    if file_extension in [".xlsx", ".xls"]:
        excel_file_to_markdown(
            input_file_path,
            num_header_rows,
            rows_per_markdown,
            base_output_dir,
            append_header,
        )
    elif file_extension == ".csv":
        csv_file_to_markdown(
            input_file_path,
            num_header_rows,
            rows_per_markdown,
            base_output_dir,
            csv_encoding,
            csv_delimiter,
            append_header,
        )
    else:
        logger.error(
            f"错误：不支持的文件类型 '{file_extension}'。请提供 Excel (.xlsx, .xls) 或 CSV (.csv) 文件。"
        )


def handler(
    cache_dir: str,
    file_name: str,
    header_rows: List[int] = [0, 1],
    data_rows: int = 12,
    append_header=True,
):
    """
    处理文件转换的主函数。
    """
    doc_id = uuid4()
    md_file_dir = os.path.join(cache_dir, str(doc_id))

    convert_file_to_markdown(
        input_file_path=file_name,
        base_output_dir=md_file_dir,
        num_header_rows=header_rows,
        rows_per_markdown=data_rows,
        append_header=append_header,
    )
    return md_file_dir, None, doc_id


if __name__ == "__main__":
    # 定义测试参数
    test_cache_dir = "/Users/tju/Desktop/"
    test_file_name = "/Users/tju/Resources/docs/excel/test_excel_v2.csv"
    test_header_rows = [0, 3]
    test_data_rows = 12
    test_append_header = True

    # Call the handler function with test parameters
    md_file_name, _, doc_id = handler(
        cache_dir=test_cache_dir,
        file_name=test_file_name,
        header_rows=test_header_rows,
        data_rows=test_data_rows,
        append_header=test_append_header,
    )

    # Output the results
    print(f"Generated Markdown file path: {md_file_name}")
    print(f"Document ID: {doc_id}")
