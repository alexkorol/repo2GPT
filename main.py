import os
import sys
import tempfile
from git import Repo, GitCommandError
from urllib.parse import urlparse
from code_consolidator import generate_consolidated_file
from sparse_priming_representor import generate_sparse_priming_representation
from tree_diagram_generator import generate_tree_diagram

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
    gitignore_file = os.path.join(local_dir, "gitignore")
    patterns = [".git", "node_modules", "package-lock.json", "yarn.lock"]
    if os.path.exists(gitignore_file):
        with open(gitignore_file, "r") as file:
            for line in file:
                line = line.strip()
                if line and not line.startswith("#"):
                    patterns.append(line)
    return patterns

def process_repository(local_dir: str) -> None:
    tree_diagram_file = "tree_diagram.txt"
    consolidated_file = "consolidated_code.txt"
    sparse_priming_file = "sparse_priming.txt"
    custom_gitignore_file = "custom_gitignore.txt"

    gitignore_patterns = load_gitignore_patterns(local_dir)

    generate_tree_diagram(local_dir, tree_diagram_file, custom_gitignore_file)
    generate_consolidated_file(local_dir, consolidated_file, custom_gitignore_file)
    generate_sparse_priming_representation(local_dir, sparse_priming_file, custom_gitignore_file)

    print(f"Tree diagram generated: {tree_diagram_file}")
    print(f"Consolidated code file generated: {consolidated_file}")
    print(f"Sparse priming file generated: {sparse_priming_file}")

def main(input_path: str) -> None:
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
        sys.exit(1)
    input_path = sys.argv[1]
    main(input_path)