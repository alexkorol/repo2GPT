import os
import fnmatch

def read_gitignore_patterns(filename):
    with open(filename, 'r') as f:
        lines = f.readlines()
    return [line.strip() for line in lines if line.strip()]

def should_ignore(file_path, ignore_patterns):
    for pattern in ignore_patterns:
        if fnmatch.fnmatch(file_path, pattern):
            return True
    return False

def generate_tree_diagram(local_dir: str, output_file: str, custom_gitignore_file: str) -> None:
    gitignore_patterns = read_gitignore_patterns(custom_gitignore_file)
    with open(output_file, "w") as f:
        for root, dirs, files in os.walk(local_dir):
            relative_root = os.path.relpath(root, local_dir)
            if should_ignore(relative_root, gitignore_patterns):
                dirs.clear()
                continue
            level = relative_root.count(os.sep)
            indent = " " * 4 * level
            f.write(f"{indent}{os.path.basename(root)}\n")
            sub_indent = " " * 4 * (level + 1)
            for file in files:
                if file.endswith('.sample'):
                    continue
                relative_file_path = os.path.join(relative_root, file)
                if should_ignore(relative_file_path, gitignore_patterns):
                    continue
                f.write(f"{sub_indent}{file}\n")

if __name__ == "__main__":
    local_dir = "."  # The directory to scan
    output_file = "tree_diagram.txt"  # The output file for the tree diagram
    custom_gitignore_file = "custom_gitignore.txt"  # The custom gitignore-like file
    generate_tree_diagram(local_dir, output_file, custom_gitignore_file)
