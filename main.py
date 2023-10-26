import os
import sys
import tempfile
import fnmatch
import re
from git import Repo, GitCommandError
from urllib.parse import urlparse
from multiprocessing import Pool
import filetype

def is_valid_url(url: str) -> bool:
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc, result.path])
    except ValueError:
        return False
    
def clone_repository(repo_url: str, local_dir: str) -> None:
    try:
        Repo.clone_from(repo_url, local_dir)
    except GitCommandError as e:
        print(f"Error cloning repository: {str(e)}")
        sys.exit(1)

def load_gitignore_patterns(local_dir: str) -> list:
    gitignore_file = os.path.join(local_dir, ".gitignore")
    patterns = [
        ".git",
        "node_modules",
        "package-lock.json",
        "yarn.lock",
    ]
    if os.path.exists(gitignore_file):
        with open(gitignore_file, "r") as file:
            for line in file:
                line = line.strip()
                if line and not line.startswith("#"):  # ignore empty lines and comments
                    patterns.append(line)
    return patterns

def process_file(file_path: str) -> str:
    # Use filetype to determine file type
    kind = filetype.guess(file_path)
    if kind is None or not kind.mime.startswith('text'):
        return ''

    # Exclude certain extensions
    ext = os.path.splitext(file_path)[-1].lower()
    if ext in ['.log', '.csv', '.md', '.txt']:  # add or modify this list to fit your needs
        return ''

    # If the file is a code file, process it
    relative_file_path = os.path.relpath(file_path, local_dir)
    if any(fnmatch.fnmatch(relative_file_path, pattern) for pattern in gitignore_patterns):
        return ''  # ignore this file
        return ''
    try:
        with open(file_path, "r", encoding="utf-8", errors='ignore') as code_file:
            return f"\n\n---\n{relative_file_path}\n---\n\n" + code_file.read()
    except UnicodeDecodeError:
        return f"Could not read the file {relative_file_path} because it is not a text file.\n"
    except Exception as e:
        return f"An error occurred while reading the file {relative_file_path}. The error is as follows:\n{str(e)}\n"

def generate_sparse_priming_representation(local_dir: str, output_file: str) -> None:
    gitignore_patterns = load_gitignore_patterns(local_dir)
    with open(output_file, "w") as f:
        for root, dirs, files in os.walk(local_dir):
            relative_root = os.path.relpath(root, local_dir)
            if any(fnmatch.fnmatch(relative_root, pattern) for pattern in gitignore_patterns):
                dirs.clear()
                continue
            for file in files:
                file_path = os.path.join(root, file)
                if file_path.endswith(('.py', '.js', '.java', '.c', '.cpp')):
                    with open(file_path, "r", encoding="utf-8", errors='ignore') as code_file:
                        lines = code_file.readlines()
                        functions = [(m.group(1), i + 1) for i, line in enumerate(lines) for m in [re.search(r"def (.+?)\(", line)] if m]
                        classes = [(m.group(1), i + 1) for i, line in enumerate(lines) for m in [re.search(r"class (.+?):", line)] if m]
                        variables = [(m.group(1), i + 1) for i, line in enumerate(lines) for m in [re.search(r"(\w+) =", line)] if m]
                        if functions or classes or variables:
                            f.write(f"\n\n---\n{os.path.relpath(file_path, local_dir)}\n---\n")
                            if functions:
                                f.write("Key functions: " + ', '.join(f"{fn} (Line {ln})" for fn, ln in functions) + f" (Total: {len(functions)})\n")
                            if classes:
                                f.write("Key classes: " + ', '.join(f"{cls} (Line {ln})" for cls, ln in classes) + f" (Total: {len(classes)})\n")
                            if variables:
                                f.write("Key variables: " + ', '.join(f"{var} (Line {ln})" for var, ln in variables) + f" (Total: {len(variables)})\n")

def process_repository(local_dir: str) -> None:
    tree_diagram_file = "tree_diagram.txt"
    consolidated_file = "consolidated_code.txt"
    sparse_priming_file = "sparse_priming.txt"

    generate_tree_diagram(local_dir, tree_diagram_file)
    generate_consolidated_file(local_dir, consolidated_file)
    generate_sparse_priming_representation(local_dir, sparse_priming_file)

    print(f"Tree diagram generated: {tree_diagram_file}")
    print(f"Consolidated code file generated: {consolidated_file}")
    print(f"Sparse priming file generated: {sparse_priming_file}")

def generate_consolidated_file(local_dir: str, output_file: str) -> None:
    """Generates a consolidated text file containing all the code files in the repository."""
    gitignore_patterns = load_gitignore_patterns(local_dir)
    ignore_patterns = [".png", ".jpg", ".csv", ".json", ".tmx"]  # Add or modify this list to fit your needs
    with open(output_file, "w") as f:
        for root, dirs, files in os.walk(local_dir):
            relative_root = os.path.relpath(root, local_dir)
            if any(fnmatch.fnmatch(relative_root, pattern) or fnmatch.fnmatch(relative_root.split(os.sep)[0], pattern) for pattern in gitignore_patterns):
                dirs.clear()  # do not descend into this directory
                continue
            for file in files:
                if file.endswith(tuple(ignore_patterns)):  # Ignore specified file types
                    continue
                file_path = os.path.join(root, file)
                relative_file_path = os.path.relpath(file_path, local_dir)
                if any(fnmatch.fnmatch(relative_file_path, pattern) for pattern in gitignore_patterns):
                    continue  # ignore this file
                f.write(f"\n\n---\n{relative_file_path}\n---\n\n")  # file name as separator
                try:
                    with open(file_path, "r", encoding="utf-8") as code_file:
                        f.write(code_file.read())
                except UnicodeDecodeError:
                    f.write(f"Could not read the file {relative_file_path} because it is not a text file.\n")
                except Exception as e:
                    f.write(f"An error occurred while reading the file {relative_file_path}. The error is as follows:\n{str(e)}\n")

def generate_tree_diagram(local_dir: str, output_file: str) -> None:
    """Generates a tree diagram of the repository's file structure."""
    gitignore_patterns = load_gitignore_patterns(local_dir)
    with open(output_file, "w") as f:
        for root, dirs, files in os.walk(local_dir):
            relative_root = os.path.relpath(root, local_dir)
            if any(fnmatch.fnmatch(relative_root, pattern) or fnmatch.fnmatch(relative_root.split(os.sep)[0], pattern) for pattern in gitignore_patterns):
                dirs.clear()  # do not descend into this directory
                continue
            level = relative_root.count(os.sep)
            indent = " " * 4 * level
            f.write(f"{indent}{os.path.basename(root)}\n")
            sub_indent = " " * 4 * (level + 1)
            for file in files:
                if file.endswith('.sample'):  # Ignore sample files
                    continue
                relative_file_path = os.path.join(relative_root, file)
                if any(fnmatch.fnmatch(relative_file_path, pattern) for pattern in gitignore_patterns):
                    continue
                f.write(f"{sub_indent}{file}\n")

def main(input_path: str) -> None:
    """Entry point of the application."""
    if is_valid_url(input_path):
        with tempfile.TemporaryDirectory() as temp_dir:
            local_dir = os.path.join(temp_dir, "repo")
            clone_repository(input_path, local_dir)
            process_repository(local_dir)
    elif os.path.isdir(input_path):
        process_repository(input_path)
    else:
        print("Invalid input. Please provide a valid GitHub repository URL or a local directory path.")
        sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) != 2 or (not is_valid_url(sys.argv[1]) and not os.path.isdir(sys.argv[1])):
        print("Usage: python main.py <valid GitHub repository URL or local directory path>")
    if len(sys.argv) != 2:
        print("Usage: python main.py <GitHub repo URL OR local dir path>")
        sys.exit(1)
    input_path = sys.argv[1]
    main(input_path)