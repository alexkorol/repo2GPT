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

# rest of the code ...

if __name__ == "__main__":
    if len(sys.argv) != 2 or not is_valid_url(sys.argv[1]):
        print("Usage: python main.py <valid GitHub repository URL>")
        sys.exit(1)
    repo_url = sys.argv[1]
    main(repo_url)
