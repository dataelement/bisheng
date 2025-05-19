import pandas as pd
from loguru import logger
import openpyxl
from typing import List
from uuid import uuid4
import os
import math
from pathlib import Path

# --- Helper Functions (unchanged from before, or slightly adapted) ---
def unmerge_and_read_sheet(sheet_obj):
    """
    Reads an openpyxl sheet object, unmerges cells by propagating the
    top-left value of a merged range to all cells in that range,
    and returns data as a list of lists.
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
    header_rows_list_of_lists, data_rows_list_of_lists, num_columns
):
    """
    Generates a Markdown table string from header and data rows.
    """
    md_lines = []
    for row_values in header_rows_list_of_lists:
        md_lines.append(
            "| "
            + " | ".join(str(v) if v is not None else "" for v in row_values)
            + " |"
        )
    if num_columns > 0:
        md_lines.append("|" + "---|" * num_columns)
    for row_values in data_rows_list_of_lists:
        md_lines.append(
            "| "
            + " | ".join(str(v) if v is not None else "" for v in row_values)
            + " |"
        )
    return "\n".join(md_lines)


# --- Core DataFrame to Markdown Processing Logic (Refactored) ---
def process_dataframe_to_markdown_files(
    df, source_name, num_header_rows, rows_per_markdown, output_dir, append_header=True
):
    """
    Processes a single DataFrame (from an Excel sheet or CSV) into paginated Markdown files.
    """
    if df.empty:
        logger.warning(f"  源 '{source_name}' 的数据DataFrame为空，跳过Markdown生成。")
        return

    num_columns = df.shape[1]

    if num_header_rows[0] < 0:
        logger.error(
            f"错误：源 '{source_name}' 的表头行数 ({num_header_rows[0]}) 不能为负。跳过。"
        )
        return
    if rows_per_markdown <= 0:
        logger.warning(
            f"错误：源 '{source_name}' 的每个Markdown文件数据行数 ({rows_per_markdown}) 必须大于0。跳过。"
        )
        return

    if num_header_rows[1] > len(df):
        logger.warning(
            f"警告：源 '{source_name}' 的总行数 ({len(df)}) 小于指定的表头行数 ({num_header_rows[1]})。"
        )
        logger.debug(f"将使用所有可用的行作为表头。")
        header_block_df = df.copy()
        data_block_df = pd.DataFrame(
            columns=df.columns
        )  # Ensure it has same columns for consistency
    else:
        header_block_df = df.iloc[num_header_rows[0]:num_header_rows[1]]
        data_block_df = df.iloc[num_header_rows[1]:]

    header_rows_as_lists = header_block_df.values.tolist()

    if data_block_df.empty:
        if not header_block_df.empty and append_header:
            logger.debug(
                f"  源 '{source_name}' 只有表头数据（或表头行数覆盖了所有数据）。正在生成表头文件..."
            )

            markdown_content = generate_markdown_table_string(
                header_rows_as_lists, [], num_columns
            )
            file_name = f"{source_name}_header_only.md"
            file_path = output_dir
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(markdown_content)
                logger.debug(f"  已保存表头文件：'{file_path}'")
            except Exception as e:
                logger.debug(f"  保存文件 '{file_path}' 时出错: {e}")
        else:
            logger.debug(
                f"  源 '{source_name}' 没有表头和数据（DataFrame完全为空），跳过。"
            )
        return

    num_data_rows_total = len(data_block_df)
    # This case should be covered by data_block_df.empty, but as a safeguard:
    if num_data_rows_total == 0:
        logger.debug(
            f"  源 '{source_name}' 没有数据行（在表头之后），已处理表头（如果存在）。"
        )
        return

    num_files_to_create = math.ceil(num_data_rows_total / rows_per_markdown)
    if (
        num_files_to_create == 0 and num_data_rows_total > 0
    ):  # Should ideally not happen with ceil
        num_files_to_create = 1

    logger.debug(
        f"  源 '{source_name}': 表头块行数: {len(header_block_df)}, 总数据行数: {num_data_rows_total}, 每文件数据行: {rows_per_markdown}"
    )
    logger.debug(
        f"  将为源 '{source_name}' 创建 {num_files_to_create} 个Markdown文件。"
    )

    for i in range(num_files_to_create):
        start_idx = i * rows_per_markdown
        end_idx = min(
            start_idx + rows_per_markdown, num_data_rows_total
        )  # Ensure not to go out of bounds
        current_data_chunk_df = data_block_df.iloc[start_idx:end_idx]
        current_data_chunk_as_lists = current_data_chunk_df.values.tolist()

        markdown_content = generate_markdown_table_string(
            header_rows_as_lists, current_data_chunk_as_lists, num_columns
        )
        part_name = (
            f"part_{i + 1}" if num_files_to_create > 1 else "full"
        )  # Simpler name if only one part

        file_name = f"{source_name}_{part_name}.md"
        file_path = os.path.join(output_dir, file_name)

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(markdown_content)
            logger.debug(
                f"  已保存：'{file_path}' (含 {len(current_data_chunk_df)} 行数据)"
            )
        except Exception as e:
            logger.debug(f"  保存文件 '{file_path}' 时出错: {e}")


# --- Excel Specific Processing ---
def excel_file_to_markdown(excel_path, num_header_rows, rows_per_markdown, output_dir, append_header=True):
    logger.debug(f"\n开始处理Excel文件：'{excel_path}'")
    try:
        # Crucial fix: read_only must be False to access merged_cells
        workbook = openpyxl.load_workbook(excel_path, data_only=True, read_only=False)
    except Exception as e:
        logger.debug(f"错误：无法加载Excel文件 '{excel_path}'。原因: {e}")
        return

    for sheet_name in workbook.sheetnames:
        logger.debug(f"\n  正在处理Excel工作表：'{sheet_name}'...")
        sheet_obj = workbook[sheet_name]

        unmerged_data_list_of_lists = unmerge_and_read_sheet(sheet_obj)

        if not unmerged_data_list_of_lists:
            logger.debug(f"  工作表 '{sheet_name}' 为空或读取失败，跳过。")
            continue

        df = pd.DataFrame(unmerged_data_list_of_lists)
        # It's crucial to fillna AFTER DataFrame creation from potentially ragged list of lists
        df.fillna("", inplace=True)

        if df.empty:  # check if DataFrame is empty after creation and fillna
            logger.debug(f"  工作表 '{sheet_name}' 处理后为空DataFrame，跳过。")
            continue

        process_dataframe_to_markdown_files(
            df,
            sheet_name,  # Source name is the sheet name
            num_header_rows,
            rows_per_markdown,
            output_dir,
            append_header=append_header
        )
    if workbook:
        workbook.close()
    logger.debug(f"\nExcel文件 '{excel_path}' 处理完成。")


# --- CSV Specific Processing ---
def csv_file_to_markdown(
    csv_path,
    num_header_rows,
    rows_per_markdown,
    output_dir,
    csv_encoding="utf-8",
    csv_delimiter=",",
    append_header = True
):
    logger.debug(f"\n开始处理CSV文件：'{csv_path}'")
    try:
        # Read CSV without auto-header, ensure all data is string initially
        # keep_default_na=False helps pandas not interpret 'NA', 'NULL' etc. as NaN if they are actual string data.
        # We'll fillna('') later for any actual missing values (e.g. empty fields ,,)
        df = pd.read_csv(
            csv_path,
            header=None,
            dtype=str,
            encoding=csv_encoding,
            sep=csv_delimiter,
            keep_default_na=False,
        )
        df.fillna("", inplace=True)  # Replace any standard NaNs that might still occur

    except pd.errors.EmptyDataError:
        logger.debug(f"错误：CSV文件 '{csv_path}' 为空。")
        return
    except FileNotFoundError:
        logger.debug(f"错误：CSV文件 '{csv_path}' 未找到。")
        return
    except Exception as e:
        logger.debug(f"错误：无法读取CSV文件 '{csv_path}'。原因: {e}")
        return

    if df.empty:
        logger.debug(f"CSV文件 '{csv_path}' 为空或处理后为空，跳过。")
        return

    # For CSV, the "source_name" will be the filename without extension
    csv_filename_base = os.path.splitext(os.path.basename(csv_path))[0]

    process_dataframe_to_markdown_files(
        df, csv_filename_base, num_header_rows, rows_per_markdown, output_dir, append_header
    )
    logger.debug(f"\nCSV文件 '{csv_path}' 处理完成。")


# --- Main Dispatcher Function ---
def convert_file_to_markdown(
    input_file_path,
    num_header_rows,
    rows_per_markdown,
    base_output_dir="output_markdown_files",
    csv_encoding="utf-8",
    csv_delimiter=",",
    append_header=True
):
    """
    Converts an Excel or CSV file to multiple Markdown files.
    """
    if not os.path.exists(input_file_path):
        logger.debug(f"错误：输入文件 '{input_file_path}' 未找到。")
        return


    if not os.path.exists(base_output_dir):
        os.makedirs(base_output_dir)
        logger.debug(f"创建输出目录：'{base_output_dir}'")

    _, file_extension = os.path.splitext(input_file_path)
    file_extension = file_extension.lower()

    if file_extension in [".xlsx", ".xls"]:
        excel_file_to_markdown(
            input_file_path, num_header_rows, rows_per_markdown, base_output_dir, append_header
        )
    elif file_extension == ".csv":
        csv_file_to_markdown(
            input_file_path,
            num_header_rows,
            rows_per_markdown,
            base_output_dir,
            csv_encoding,
            csv_delimiter,
            append_header
        )
    else:
        logger.debug(
            f"错误：不支持的文件类型 '{file_extension}'。请提供 Excel (.xlsx, .xls) 或 CSV (.csv) 文件。"
        )


def handler(cache_dir, file_name: str, header_rows: List[int] = [0, 1], data_rows: int = 12, append_header=True):

    """
    处理文件转换的主函数。

    参数:
    file_name (str): 输入的 Word 文档路径。
    knowledge_id (str): 知识 ID，用于生成输出文件名。
    """
    doc_id = uuid4()
    md_file_name = f"{cache_dir}/{doc_id}"

    convert_file_to_markdown(
        input_file_path=file_name,
        base_output_dir=md_file_name,
        num_header_rows=header_rows,
        rows_per_markdown=data_rows,
        append_header=append_header,
    )
    return md_file_name, None, doc_id
