import os
import sys
import tempfile
import requests
from git import Repo, GitCommandError
from pathlib import Path
from urllib.parse import urlparse

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

def generate_tree_diagram(local_dir: str, output_file: str) -> None:
    """Generates a tree diagram of the repository's file structure."""
    with open(output_file, "w") as f:
        for root, dirs, files in os.walk(local_dir):
            level = root.replace(local_dir, "").count(os.sep)
            indent = " " * 4 * level
            f.write(f"{indent}{os.path.basename(root)}\n")
            sub_indent = " " * 4 * (level + 1)
            for file in files:
                f.write(f"{sub_indent}{file}\n")

def generate_consolidated_file(local_dir: str, output_file: str) -> None:
    """Generates a consolidated text file containing all the code files in the repository."""
    with open(output_file, "w") as f:
        for root, dirs, files in os.walk(local_dir):
            for file in files:
                file_path = os.path.join(root, file)
                f.write(f"\n\n{'=' * 80}\n{file_path}\n{'=' * 80}\n\n")
                with open(file_path, "r", errors="ignore") as code_file:
                    f.write(code_file.read())

def main(repo_url: str) -> None:
    """Entry point of the application."""
    with tempfile.TemporaryDirectory() as temp_dir:
        local_dir = os.path.join(temp_dir, "repo")
        clone_repository(repo_url, local_dir)
        tree_diagram_file = "tree_diagram.txt"
        consolidated_file = "consolidated_code.txt"
        generate_tree_diagram(local_dir, tree_diagram_file)
        generate_consolidated_file(local_dir, consolidated_file)
        print(f"Tree diagram generated: {tree_diagram_file}")
        print(f"Consolidated code file generated: {consolidated_file}")

if __name__ == "__main__":
    if len(sys.argv) != 2 or not is_valid_url(sys.argv[1]):
        print("Usage: python main.py <valid GitHub repository URL>")
        sys.exit(1)
    repo_url = sys.argv[1]
    main(repo_url)
