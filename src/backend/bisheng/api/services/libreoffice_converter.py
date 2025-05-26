import subprocess
import os
import shutil # For checking if the executable is in PATH

def get_libreoffice_path():
    """
    Tries to find the LibreOffice executable.
    prerequisites:

    1. install unoconv libreoffice
    2. linux:
        sudo apt-get install unoconv libreoffice
        sudo yum install unoconv libreoffice-headless
    3. macos:
        brew install unoconv libreoffice
    """
    if shutil.which("soffice"):
        return "soffice"
    if shutil.which("libreoffice"):
        return "libreoffice"
    # Common Windows paths
    windows_paths = [
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"
    ]
    for path in windows_paths:
        if os.path.exists(path):
            return path
    return None

def convert_doc_to_docx(input_doc_path, output_dir=None):
    """
    Converts a .doc file to .docx using LibreOffice/soffice command line.

    Args:
        input_doc_path (str): The absolute path to the input .doc file.
        output_dir (str, optional): The directory to save the converted .docx file.
                                    If None, saves in the same directory as the input file.
        libreoffice_exec (str, optional): The command name or full path of the
                                          LibreOffice executable (e.g., 'libreoffice',
                                          'soffice', or '/opt/libreoffice7.x/program/soffice').

    Returns:
        str: The path to the converted .docx file if successful, None otherwise.
    """
    if not os.path.isabs(input_doc_path):
        input_doc_path = os.path.abspath(input_doc_path)

    if not input_doc_path.lower().endswith(".doc"):
        print(f"Error: Input file '{input_doc_path}' is not a .doc file.")
        return None

    if not os.path.exists(input_doc_path):
        print(f"Error: Input file not found at '{input_doc_path}'")
        return None

    # Determine output directory
    if output_dir is None:
        output_dir = os.path.dirname(input_doc_path)
    else:
        if not os.path.isabs(output_dir):
            output_dir = os.path.abspath(output_dir)
        if not os.path.exists(output_dir):
            try:
                os.makedirs(output_dir, exist_ok=True)
                print(f"Created output directory: '{output_dir}'")
            except OSError as e:
                print(f"Error creating output directory '{output_dir}': {e}")
                return None

    # Check if libreoffice_exec is in PATH if it's not a full path
    soffice_path = get_libreoffice_path()
    if not soffice_path:
        print("Error: LibreOffice (soffice) command not found. Please install LibreOffice and ensure it's in your PATH, or adjust 'get_libreoffice_path()'.")
        return False


    # Construct the output .docx file path
    base_name = os.path.basename(input_doc_path)
    file_name_no_ext = os.path.splitext(base_name)[0]
    output_docx_path = os.path.join(output_dir, f"{file_name_no_ext}.docx")

    command = [
        soffice_path,
        '--headless',         # Run in headless mode (no GUI)
        '--convert-to', 'docx', # Specify the output format
        '--outdir', output_dir, # Specify the output directory
        input_doc_path        # The input file
    ]

    print(f"Executing command: {' '.join(command)}")

    try:
        process = subprocess.run(command, check=True, capture_output=True, text=True, timeout=120) # 120 seconds timeout
        print(f"LibreOffice STDOUT: {process.stdout}")
        if process.stderr: # LibreOffice sometimes prints info to stderr even on success
            print(f"LibreOffice STDERR: {process.stderr}")

        # Check if the file was actually created
        # LibreOffice creates the file with the correct name in the output_dir
        expected_file_in_outdir = os.path.join(output_dir, f"{file_name_no_ext}.docx")
        if os.path.exists(expected_file_in_outdir):
            # If output_docx_path is different (it shouldn't be with this logic, but for safety)
            if expected_file_in_outdir != output_docx_path:
                shutil.move(expected_file_in_outdir, output_docx_path)
            print(f"Successfully converted '{input_doc_path}' to '{output_docx_path}'")
            return output_docx_path
        else:
            # This case should ideally not happen if subprocess.run didn't raise an error
            # and LibreOffice worked as expected.
            print(f"Error: Conversion command seemed to succeed, but output file '{expected_file_in_outdir}' not found.")
            print("Please check LibreOffice's behavior and output directory permissions.")
            return None

    except FileNotFoundError:
        print(f"Error: The LibreOffice executable '{soffice_path}' was not found.")
        print("Ensure LibreOffice is installed and the command is in your PATH or provide the full path.")
        return None
    except subprocess.CalledProcessError as e:
        print(f"Error during LibreOffice conversion for '{input_doc_path}':")
        print(f"Command: {' '.join(e.cmd)}")
        print(f"Return code: {e.returncode}")
        print(f"STDOUT: {e.stdout}")
        print(f"STDERR: {e.stderr}")
        return None
    except subprocess.TimeoutExpired:
        print(f"Error: LibreOffice conversion for '{input_doc_path}' timed out.")
        return None
    except Exception as e:
        print(f"An unexpected error occurred during conversion of '{input_doc_path}': {e}")
        return None

def convert_ppt_to_pdf(input_path, output_dir=None):
    """
    Converts .ppt or .pptx to PDF using LibreOffice soffice command.

    Args:
        input_path (str): Path to the .ppt or .pptx file.
        output_dir (str, optional): Directory to save the PDF.
                                    Defaults to the same directory as the input file.
    """
    if not (input_path.lower().endswith(".ppt") or input_path.lower().endswith(".pptx")):
        print(f"Error: {input_path} is not a .ppt or .pptx file.")
        return False

    if not os.path.exists(input_path):
        print(f"Error: File not found at {input_path}")
        return False

    soffice_path = get_libreoffice_path()
    if not soffice_path:
        print("Error: LibreOffice (soffice) command not found. Please install LibreOffice and ensure it's in your PATH, or adjust 'get_libreoffice_path()'.")
        return False

    if not output_dir:
        output_dir = os.path.dirname(input_path)
    else:
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

    # The output PDF will have the same name as the input file, but with a .pdf extension,
    # and will be placed in the output_dir.
    base_name = os.path.basename(input_path)
    pdf_name = os.path.splitext(base_name)[0] + ".pdf"
    expected_pdf_path = os.path.join(output_dir, pdf_name)

    command = [
        soffice_path,
        '--headless',
        '--convert-to', 'pdf',
        '--outdir', output_dir,
        input_path
    ]

    try:
        print(f"Converting {input_path} to PDF using {soffice_path}...")
        # LibreOffice can sometimes be slow to start up and convert.
        # It may also not provide much stdout/stderr unless there's a significant error.
        process = subprocess.run(command, capture_output=True, text=True, check=True, timeout=180) # 180 seconds timeout

        if process.stdout:
            print(f"soffice stdout: {process.stdout}") # Often empty on success
        if process.stderr:
            print(f"soffice stderr: {process.stderr}") # Check for any warnings/errors

        if os.path.exists(expected_pdf_path):
            print(f"Successfully converted {input_path} to {expected_pdf_path}")
            return True
        else:
            print(f"Conversion command ran, but output PDF not found at expected location: {expected_pdf_path}")
            print("Please check LibreOffice's behavior. Stdout/Stderr from above might provide clues.")
            return False

    except FileNotFoundError: # Should be caught by get_libreoffice_path, but as a fallback
        print(f"Error: {soffice_path} command not found. Please install LibreOffice and ensure it's in your PATH.")
        return False
    except subprocess.CalledProcessError as e:
        print(f"Error during soffice conversion for {input_path}: {e}")
        print(f"Exit code: {e.returncode}")
        print(f"Stdout: {e.stdout}")
        print(f"Stderr: {e.stderr}")
        # LibreOffice might return a non-zero exit code even for some warnings.
        # Check if the file was created anyway.
        if os.path.exists(expected_pdf_path):
            print(f"Warning: soffice returned an error code, but PDF was created at {expected_pdf_path}")
            return True
        return False
    except subprocess.TimeoutExpired:
        print(f"Error: soffice conversion for {input_path} timed out.")
        # Check if the file was partially created or created despite timeout
        if os.path.exists(expected_pdf_path):
            print(f"Warning: soffice timed out, but PDF might have been created at {expected_pdf_path}")
            return True
        return False
    except Exception as e:
        print(f"An unexpected error occurred with soffice for {input_path}: {e}")
        return False



if __name__ == "__main__":
    file_name = "/Users/tju/Desktop/2307.09288.docx"
    print(f"{os.path.basename(file_name)}/x")