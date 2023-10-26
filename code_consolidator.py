import os
import fnmatch

def read_gitingnore_patterns(filename):
    with open(filename, 'r') as f:
        lines = f.readlines()
    return [line.strip() for line in lines if line.strip()]

def should_ignore(file_path, ignore_patterns):
    for pattern in ignore_patterns:
        if fnmatch.fnmatch(file_path, pattern):
            return True
    return False

def generate_consolidated_file(local_dir: str, output_file: str, custom_gitingnore_file: str) -> None:
    gitignore_patterns = read_gitingnore_patterns(custom_gitingnore_file)
    hard_coded_ignore_patterns = [".png", ".jpg", ".csv", ".json", ".tmx"]

    with open(output_file, "w") as f:
        for root, dirs, files in os.walk(local_dir):
            relative_root = os.path.relpath(root, local_dir)
            if should_ignore(relative_root, gitignore_patterns):
                dirs.clear()
                continue
            for file in files:
                file_path = os.path.join(root, file)
                relative_file_path = os.path.relpath(file_path, local_dir)
                if should_ignore(relative_file_path, gitignore_patterns) or should_ignore(relative_file_path, hard_coded_ignore_patterns):
                    continue
                f.write(f"\n\n---\n{relative_file_path}\n---\n\n")
                try:
                    with open(file_path, "r", encoding="utf-8") as code_file:
                        f.write(code_file.read())
                except UnicodeDecodeError:
                    f.write(f"Could not read the file {relative_file_path} because it is not a text file.\n")
                except Exception as e:
                    f.write(f"An error occurred while reading the file {relative_file_path}. The error is as follows:\n{str(e)}\n")

if __name__ == "__main__":
    local_dir = "."  # The directory to scan
    output_file = "consolidated_code.txt"  # The output file
    custom_gitingnore_file = "custom_gitingnore.txt"  # The custom gitignore-like file
    generate_consolidated_file(local_dir, output_file, custom_gitingnore_file)
