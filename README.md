# Repo2GPT
Repo2GPT is a Python application that clones a GitHub repository and generates a tree diagram of the repository's file structure and a consolidated text file containing all the code files in the repository. This utility can help in quickly understanding the structure of a repository and reviewing its code. 

...

### Install the Required Packages:

With the virtual environment activated, install the packages listed in `requirements.txt`:

```bash
pip install -r requirements.txt
```

Note: If you're running this on a Windows system, you might need to replace `python-magic==0.4.22` with `python-magic-bin==0.4.14` in `requirements.txt` before running the `pip install -r requirements.txt` command. As of recent updates, you may also need to install the `filetype` package for identifying file types correctly.

...

## Usage

With everything set up, you can now use Repo2GPT:

```bash
python main.py <GitHub repository URL>
```

Replace `<GitHub repository URL>` with the URL of the repository you want to clone and analyze. 

Repo2GPT will generate a tree diagram of the repository's structure and a consolidated text file containing all the code in the repository. The files will be named `tree_diagram.txt` and `consolidated_code.txt`, respectively.

## Future plans

* Web version
* Ability to use repo2GPT on local folders
* Account for ignoring more types of irrelevant metadata files
* Add splitting of consolidated code into custom lengths
* Better identification of code files and non-code files

## License

Repo2GPT is licensed under the terms of the MIT license. See [LICENSE](LICENSE) for more details.



