import pandas as pd
from loguru import logger
import openpyxl
from typing import List
from uuid import uuid4
import os
import math
from pathlib import Path



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
                + " | ".join(str(v) if v is not None else "" for v in row_values)
                + " |"
            )

        # 在第一行表头下方插入Markdown分隔符
        if num_columns > 0:
            md_lines.append("|" + "---|" * num_columns)

        post_separator_header = header_rows_list_of_lists[separator_placement_index:]
        for row_values in post_separator_header:
            md_lines.append(
                "| "
                + " | ".join(str(v) if v is not None else "" for v in row_values)
                + " |"
            )

    # 总是处理数据行
    for row_values in data_rows_list_of_lists:
        md_lines.append(
            "| "
            + " | ".join(str(v) if v is not None else "" for v in row_values)
            + " |"
        )

    return "\n".join(md_lines)


def process_dataframe_to_markdown_files(
    df, source_name, num_header_rows, rows_per_markdown, output_dir, append_header=True
):
    """
    **FINAL VERSION**: 根据 append_header 正确定义数据区和表头区。
    - append_header=True: 按 num_header_rows 分离表头和数据。
    - append_header=False: 全部内容视为数据，表头为空，忽略 num_header_rows。
    """
    if df.empty:
        logger.warning(f"  源 '{source_name}' 的数据DataFrame为空，跳过Markdown生成。")
        return

    num_columns = df.shape[1]

    # --- 核心逻辑修改：根据 append_header 决定如何切分数据 ---
    if append_header:
        # 当需要表头时，执行“包含首尾”逻辑
        try:
            start_header_idx, end_header_idx = num_header_rows[0], num_header_rows[1]
            # Python iloc切片是“含头不含尾”，所以 B 需要 +1
            header_slice = slice(start_header_idx, end_header_idx + 1)

            if not (0 <= start_header_idx <= end_header_idx < len(df)):
                logger.error(
                    f"错误：源 '{source_name}' 的表头参数 [A, B] = [{start_header_idx}, {end_header_idx}] 无效。索引超出范围。跳过。"
                )
                return

            header_block_df = df.iloc[header_slice]
            data_block_df = df.drop(df.index[header_slice]).reset_index(drop=True)
            header_rows_as_lists = header_block_df.values.tolist()

        except (IndexError, TypeError):
            logger.error(
                f"错误：源 '{source_name}' 的表头参数 'num_header_rows' 格式不正确。应为 [A, B] 形式，例如 [2, 4]。跳过。"
            )
            return
    else:
        # 当不需要表头时，整个DataFrame都是数据
        header_block_df = pd.DataFrame()  # 表头块为空
        data_block_df = df.copy()  # 数据块为全部内容
        header_rows_as_lists = []  # 传递给生成器的表头为空列表

    # --- 后续分页逻辑基于上面正确定义的 data_block_df 和 header_rows_as_lists ---

    if data_block_df.empty:
        if append_header and not header_block_df.empty:
            markdown_content = generate_markdown_table_string(
                header_rows_as_lists, [], num_columns
            )
            file_name = f"{source_name}_header_only.md"
            file_path = os.path.join(output_dir, file_name)
            file_path = os.path.join(output_dir, file_name)
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(markdown_content)
                logger.debug(f"  已保存仅含表头的文件：'{file_path}'")
            except Exception as e:
                logger.debug(f"  保存文件 '{file_path}' 时出错: {e}")
        return

    num_data_rows_total = len(data_block_df)
    num_files_to_create = math.ceil(num_data_rows_total / rows_per_markdown)
    if num_files_to_create == 0 and num_data_rows_total > 0:
        num_files_to_create = 1

    logger.debug(
        f"  源 '{source_name}': 表头块行数: {len(header_rows_as_lists)}, 总数据行数: {num_data_rows_total}, 每文件数据行: {rows_per_markdown}"
    )
    logger.debug(
        f"  将为源 '{source_name}' 创建 {num_files_to_create} 个Markdown文件。"
    )

    for i in range(num_files_to_create):
        start_idx = i * rows_per_markdown
        end_idx = min(start_idx + rows_per_markdown, num_data_rows_total)
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
            logger.debug(f"  保存文件 '{file_path}' 时出错: {e}")


def excel_file_to_markdown(
    excel_path, num_header_rows, rows_per_markdown, output_dir, append_header=True
):
    logger.debug(f"\n开始处理Excel文件：'{excel_path}'")
    try:
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
        df.fillna("", inplace=True)

        if df.empty:
            logger.debug(f"  工作表 '{sheet_name}' 处理后为空DataFrame，跳过。")
            continue

        process_dataframe_to_markdown_files(
            df,
            sheet_name,
            sheet_name,
            num_header_rows,
            rows_per_markdown,
            output_dir,
            append_header=append_header,
            append_header=append_header,
        )
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

    csv_filename_base = os.path.splitext(os.path.basename(csv_path))[0]
    process_dataframe_to_markdown_files(
        df,
        csv_filename_base,
        num_header_rows,
        rows_per_markdown,
        output_dir,
        append_header,
    )


def convert_file_to_markdown(
    input_file_path,
    num_header_rows,
    rows_per_markdown,
    base_output_dir="output_markdown_files",
    csv_encoding="utf-8",
    csv_delimiter=",",
    append_header=True,
    append_header=True,
):
    """
    将 Excel 或 CSV 文件转换为多个 Markdown 文件。
    将 Excel 或 CSV 文件转换为多个 Markdown 文件。
    """
    if not os.path.exists(input_file_path):
        logger.debug(f"错误：输入文件 '{input_file_path}' 未找到。")
        return

    if not os.path.exists(base_output_dir):
        os.makedirs(base_output_dir)

    _, file_extension = os.path.splitext(input_file_path)
    file_extension = file_extension.lower()

    if file_extension in [".xlsx", ".xls"]:
        excel_file_to_markdown(
            input_file_path,
            num_header_rows,
            rows_per_markdown,
            base_output_dir,
            append_header,
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
    test_file_name = "/Users/tju/Resources/docs/excel/test_excel_v2.xlsx"
    test_header_rows = [8, 4]
    test_data_rows = 5
    test_append_header = True

    # Call the handler function with test parameters
    md_file_name, _, doc_id = handler(
        cache_dir=test_cache_dir,
        file_name=test_file_name,
        header_rows=test_header_rows,
        data_rows=test_data_rows,
        append_header=test_append_header,
    )
