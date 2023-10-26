import os
import re
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

def generate_sparse_priming_representation(local_dir: str, output_file: str, custom_gitignore_file: str) -> None:
    gitignore_patterns = read_gitingnore_patterns(custom_gitignore_file)
    with open(output_file, "w") as f:
        for root, dirs, files in os.walk(local_dir):
            relative_root = os.path.relpath(root, local_dir)
            if should_ignore(relative_root, gitignore_patterns):
                dirs.clear()
                continue
            for file in files:
                file_path = os.path.join(root, file)
                relative_file_path = os.path.relpath(file_path, local_dir)
                if should_ignore(relative_file_path, gitignore_patterns):
                    continue
                if file_path.endswith(('.py', '.js', '.java', '.c', '.cpp')):
                    with open(file_path, "r", encoding="utf-8", errors='ignore') as code_file:
                        lines = code_file.readlines()
                        functions = [(m.group(1), i + 1) for i, line in enumerate(lines) for m in [re.search(r"def (.+?)\(", line)] if m]
                        classes = [(m.group(1), i + 1) for i, line in enumerate(lines) for m in [re.search(r"class (.+?):", line)] if m]
                        variables = [(m.group(1), i + 1) for i, line in enumerate(lines) for m in [re.search(r"(\w+) =", line)] if m]
                        if functions or classes or variables:
                            f.write(f"\n\n---\n{relative_file_path}\n---\n")
                            if functions:
                                f.write("Key functions: " + ', '.join(f"{fn} (Line {ln})" for fn, ln in functions) + f" (Total: {len(functions)})\n")
                            if classes:
                                f.write("Key classes: " + ', '.join(f"{cls} (Line {ln})" for cls, ln in classes) + f" (Total: {len(classes)})\n")
                            if variables:
                                f.write("Key variables: " + ', '.join(f"{var} (Line {ln})" for var, ln in variables) + f" (Total: {len(variables)})\n")

if __name__ == "__main__":
    local_dir = "."  # The directory to scan
    output_file = "sparse_priming.txt"  # The output file for the sparse priming representation
    custom_gitignore_file = "custom_gitingnore.txt"  # The custom gitignore-like file
    generate_sparse_priming_representation(local_dir, output_file, custom_gitignore_file)