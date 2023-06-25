# Repo2GPT
Repo2GPT is a Python application that clones a GitHub repository and generates a tree diagram of the repository's file structure and a consolidated text file containing all the code files in the repository. This utility can help in quickly understanding the structure of a repository and reviewing its code. 

...

### Install the Required Packages:

With the virtual environment activated (optional), install the packages listed in `requirements.txt`:

```bash
pip install -r requirements.txt
```

...

## Usage

With everything set up, you can now use Repo2GPT:

```bash
python main.py <GitHub repository URL or local directory path>
```

Replace <GitHub repository URL or local directory path> with the URL of the repository you want to clone and analyze, or a local directory path you want to analyze.

Repo2GPT will generate a tree diagram of the repository's structure and a consolidated text file containing all the code in the repository. The files will be named tree_diagram.txt and consolidated_code.txt, respectively.

## Future plans

* Web version
* Ability to use repo2GPT on local folders
* Account for ignoring more types of irrelevant metadata files
* Add splitting of consolidated code into custom lengths
* Better identification of code files and non-code files

## License

Repo2GPT is licensed under the terms of the MIT license. See [LICENSE](LICENSE) for more details.



