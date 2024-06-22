# Repo2GPT
Repo2GPT is a Python application that clones a GitHub repository and generates a detailed repository map (repomap) of the repository's file structure, including classes, methods, and functions in each code file, and a consolidated text file containing all the code files in the repository. This utility can help in quickly understanding the structure of a repository and reviewing its code. This simplifies the process of iterative development using LLMs such as GPT-4. Another use case for it is analyzing a given repo for malicious code using ChatGPT.

Repo2GPT can also be used on a local folder containing code if no repo is available for the project you are trying to consolidate.

### Install the Required Packages:

With the virtual environment activated (optional), install the packages listed in `requirements.txt`:

```bash
pip install -r requirements.txt
```

## Usage

With everything set up, you can now use Repo2GPT:

```bash
python main.py <GitHub repository URL or local directory path>
```

Replace `<GitHub repository URL or local directory path>` with the URL of the repository you want to clone and analyze, or a local directory path you want to analyze.

Repo2GPT will generate a detailed repository map named `repomap.txt` and a consolidated text file containing all the code in the repository named `consolidated_code.txt`.

## Future plans

* Add ASM Traversal and mapping similar to ctags.
* Web version or VS Code Extension.
* Account for ignoring more types of irrelevant metadata files.
* Fix some of the encoding errors when consolidating certain readme.md files.
* Better identification of code files and non-code files.

## License

Repo2GPT is licensed under the terms of the MIT license. See [LICENSE](LICENSE) for more details.
