import math
import os
from typing import List
from uuid import uuid4

import openpyxl
import pandas as pd
from loguru import logger


def xls_to_xlsx(xls_path):
    if not xls_path.lower().endswith(".xls"):
        return None

    if not os.path.exists(xls_path):
        return None

    try:
        xls_file = pd.ExcelFile(xls_path)
        sheets_to_write = {}

        # 2. 遍历所有工作表，检查是否为空，并将非空内容存入字典
        for sheet_name in xls_file.sheet_names:
            df = xls_file.parse(sheet_name)
            # df.empty 会判断 DataFrame 是否无数据（行数为0）
            if not df.empty:
                sheets_to_write[sheet_name] = df
            else:
                #  丢弃空工作表
                pass

        # 3. 如果没有任何非空工作表，则不创建新文件
        if not sheets_to_write:
            return None

        # 4. 如果存在非空工作表，则写入新文件
        xlsx_path = os.path.splitext(xls_path)[0] + ".xlsx"
        with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
            for sheet_name, df in sheets_to_write.items():
                df.to_excel(writer, sheet_name=sheet_name, index=False)

        return xlsx_path

    except Exception as e:
        return None


def remove_characters(s, chars_to_remove=["\n", "\r"]):
    """
    从字符串中移除指定的字符。
    """
    if not isinstance(s, str):
        return s
    for char in chars_to_remove:
        s = s.replace(char, "")
    return s.strip()


def unmerge_and_read_sheet(sheet_obj):
    """
    读取 openpyxl 工作表对象，通过将合并区域左上角的值填充到该区域的所有单元格中来取消合并单元格，
    并以列表的列表形式返回数据。
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
        separator_placement_index=1,
):
    """
    根据新规则生成Markdown表格字符串。
    如果header_rows_list_of_lists为空，则不生成表头和分隔符。
    """
    md_lines = []

    # 只有在提供了表头行时，才处理表头和分隔符
    if header_rows_list_of_lists:
        pre_separator_header = header_rows_list_of_lists[:separator_placement_index]
        for row_values in pre_separator_header:
            md_lines.append(
                "| "
                + " | ".join(
                    remove_characters(str(v)) if v is not None else ""
                    for v in row_values
                )
                + " |"
            )

        # 在第一行表头下方插入Markdown分隔符
        if num_columns > 0:
            md_lines.append("|" + "---|" * num_columns)

        post_separator_header = header_rows_list_of_lists[separator_placement_index:]
        for row_values in post_separator_header:
            md_lines.append(
                "| "
                + " | ".join(
                    remove_characters(str(v)) if v is not None else ""
                    for v in row_values
                )
                + " |"
            )

    # 总是处理数据行
    for row_values in data_rows_list_of_lists:
        md_lines.append(
            "| "
            + " | ".join(
                remove_characters(str(v)) if v is not None else "" for v in row_values
            )
            + " |"
        )

    return "\n".join(md_lines)


def process_dataframe_to_markdown_files(
        df,
        sheet_index: str,
        num_header_rows,
        rows_per_markdown,
        output_dir,
        append_header=True,
):
    """
    - append_header=True: 按 num_header_rows 分离表头和数据。
    - append_header=False: 全部内容视为数据，表头为空，忽略 num_header_rows。
    """
    if df.empty:
        logger.warning(f"  源 '{sheet_index}' 的数据DataFrame为空，跳过Markdown生成。")
        return

    num_columns = df.shape[1]
    rows = df.shape[0]

    if rows == 0 or num_columns == 0:
        return

    header_block_df = pd.DataFrame()
    start_header_idx, end_header_idx = num_header_rows[0], num_header_rows[1]
    if start_header_idx >= rows:
        append_header = False

    # --- 核心逻辑修改：根据 append_header 决定如何切分数据 ---
    if append_header:
        # 根据用户规则处理表头索引越界问题
        if start_header_idx >= rows:
            logger.warning(f"  表头起始行 {start_header_idx} 超出总行数 {rows}。将使用第一行作为表头。")
            start_header_idx, end_header_idx = 0, 0
        elif end_header_idx >= rows:
            logger.warning(f"  表头结束行 {end_header_idx} 超出总行数 {rows}。将截断至最后一行。")
            end_header_idx = rows - 1

        # 确保索引合法
        if start_header_idx < 0: start_header_idx = 0
        if end_header_idx < start_header_idx: end_header_idx = start_header_idx

        try:
            header_slice = slice(start_header_idx, end_header_idx + 1)
            header_block_df = df.iloc[header_slice]
            data_block_df = df.drop(df.index[header_slice]).reset_index(drop=True)
            header_rows_as_lists = header_block_df.values.tolist()
        except Exception as e:
            logger.error(
                f"  在源 '{sheet_index}' 中根据表头索引 [{start_header_idx}, {end_header_idx}] 切分数据时出错: {e}。跳过。")
            return
    else:
        # 当 append_header 为 False 时，所有内容都视为数据，表头列表为空
        header_rows_as_lists = []
        data_block_df = df.reset_index(drop=True)

    # --- 后续分页逻辑 ---
    if data_block_df.empty:
        if append_header and not header_block_df.empty:
            markdown_content = generate_markdown_table_string(
                header_rows_as_lists, [], num_columns
            )
            # BUG FIX: Use zfill for proper padding. This is file '000' for the sheet.
            file_name = f"{str(sheet_index).zfill(2)}000.md"
            file_path = os.path.join(output_dir, file_name)
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(markdown_content)
                logger.debug(f"  已保存仅含表头的文件：'{file_path}'")
            except Exception as e:
                logger.debug(f"  保存文件 '{file_path}' 时出错: {e}")
        return

    num_data_rows_total = len(data_block_df)
    num_files_to_create = math.ceil(num_data_rows_total / rows_per_markdown) if rows_per_markdown > 0 else (
        1 if num_data_rows_total > 0 else 0)

    for i in range(num_files_to_create):
        start_idx = i * rows_per_markdown
        end_idx = min(start_idx + rows_per_markdown, num_data_rows_total)
        current_data_chunk_as_lists = data_block_df.iloc[start_idx:end_idx].values.tolist()

        final_header_for_chunk = header_rows_as_lists
        final_data_for_chunk = current_data_chunk_as_lists

        # 如果不附加真实表头，并且当前数据块不为空，则将数据的第一行用作“伪表头”以生成分隔符
        if not append_header and current_data_chunk_as_lists:
            final_header_for_chunk = [current_data_chunk_as_lists[0]]
            final_data_for_chunk = current_data_chunk_as_lists[1:]

        markdown_content = generate_markdown_table_string(
            final_header_for_chunk, final_data_for_chunk, num_columns
        )

        # BUG FIX: Use zfill for proper 2-digit sheet and 3-digit file padding.
        file_name = f"{str(sheet_index).zfill(2)}{str(i).zfill(3)}.md"
        file_path = os.path.join(output_dir, file_name)

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(markdown_content)
            logger.debug(
                f"  已保存：'{file_path}' (含 {len(current_data_chunk_as_lists)} 行原始数据)"
            )
        except Exception as e:
            logger.debug(f"  保存文件 '{file_path}' 时出错: {e}")


def is_list_of_lists_empty(data_list):
    """
    判断一个二维列表是否为空或只包含空值 (None, '')。
    """
    if not data_list:
        return True
    # 使用 any() 和生成器表达式，高效判断
    # any(row) 检查是否存在非空行
    # any(cell is not None and cell != '' for cell in row) 检查行内是否有非空单元格
    return not any(any(cell is not None and str(cell).strip() != '' for cell in row) for row in data_list)


def excel_file_to_markdown(
        excel_path, num_header_rows, rows_per_markdown, output_dir, append_header=True
):
    logger.debug(f"\n开始处理Excel文件：'{excel_path}'")
    try:
        workbook = openpyxl.load_workbook(excel_path, data_only=True, read_only=False)
    except Exception as e:
        logger.debug(f"错误：无法加载Excel文件 '{excel_path}'。原因: {e}")
        return

    sheet_index = 0
    for sheet_name in workbook.sheetnames:
        logger.debug(f"\n  正在处理Excel工作表：'{sheet_name}'...")
        sheet_obj = workbook[sheet_name]
        unmerged_data_list_of_lists = unmerge_and_read_sheet(sheet_obj)

        # 使用新的判断函数
        if is_list_of_lists_empty(unmerged_data_list_of_lists):
            logger.debug(f"  工作表 '{sheet_name}' 为空或无有效数据，跳过。")
            continue

        df = pd.DataFrame(unmerged_data_list_of_lists)
        df.fillna("", inplace=True)
        if df.empty:
            logger.debug(f"  工作表 '{sheet_name}' 处理后为空DataFrame，跳过。")
            continue

        process_dataframe_to_markdown_files(
            df,
            str(sheet_index),
            num_header_rows,
            rows_per_markdown,
            output_dir,
            append_header=append_header,
        )
        sheet_index += 1

    if workbook:
        workbook.close()
    logger.debug(f"\nExcel文件 '{excel_path}' 处理完成。")


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
        df = pd.read_csv(
            csv_path,
            header=None,
            dtype=str,
            encoding=csv_encoding,
            sep=csv_delimiter,
            keep_default_na=False,
        )
        df.fillna("", inplace=True)

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

    process_dataframe_to_markdown_files(
        df,
        "0",
        num_header_rows,
        rows_per_markdown,
        output_dir,
        append_header,
    )
    logger.debug(f"\nCSV文件 '{csv_path}' 处理完成。")


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
        logger.debug(f"错误：输入文件 '{input_file_path}' 未找到。")
        return

    if not os.path.exists(base_output_dir):
        os.makedirs(base_output_dir)
        logger.debug(f"创建输出目录：'{base_output_dir}'")

    _, file_extension = os.path.splitext(input_file_path)
    file_extension = file_extension.lower()
    if file_extension == ".xls":
        input_file_path = xls_to_xlsx(input_file_path)

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
        logger.debug(
            f"错误：不支持的文件类型 '{file_extension}'。请提供 Excel (.xlsx, .xls) 或 CSV (.csv) 文件。"
        )


def handler(
        cache_dir,
        file_name: str,
        header_rows: List[int] = [0, 1],
        data_rows: int = 12,
        append_header=True,
):
    """
    处理文件转换的主函数。
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


if __name__ == "__main__":
    # 定义测试参数
    test_cache_dir = "/Users/tju/Desktop/"
    test_file_name = "/Users/tju/Downloads/bug1.xlsx"
    # 测试 append_header=True 且索引越界的情况
    test_header_rows = [0, 0]  # start_header_index 超出范围
    test_data_rows = 2
    test_append_header = True

    # 调用 handler 函数
    print("--- 测试场景: append_header=True, 表头索引越界 ---")
    handler(
        cache_dir=test_cache_dir,
        file_name=test_file_name,
        header_rows=test_header_rows,
        data_rows=test_data_rows,
        append_header=test_append_header,
    )
