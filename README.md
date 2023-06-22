# Repo2GPT
Repo2GPT is a Python application that clones a GitHub repository and generates a tree diagram of the repository's file structure and a consolidated text file containing all the code files in the repository. This utility can help in quickly understanding the structure of a repository and reviewing its code. 

## Installation and Setup

### Prerequisites
You need Python 3.6 or later to run Repo2GPT. You can have multiple Python versions (2.x and 3.x) installed on the same system without problems.

In Ubuntu, Mint and Debian you can install Python 3 like this:

~~~
sudo apt-get install python3 python3-pip
~~~

For other Linux flavors, macOS and Windows, packages are available at

http://www.python.org/getit/

### Clone the Repository:

To get started, clone the repository to your local machine:

~~~bash
git clone https://github.com/alexkorol/repo2gpt.git
cd repo2gpt
~~~

### Set Up a Python Virtual Environment:

While this step is optional, it is recommended to avoid conflicts between package versions:

~~~bash
python -m venv venv
source venv/bin/activate
~~~

On Windows, you might need to use a slightly different command to activate the environment:

~~~bash
venv\Scripts\activate
~~~

### Install the Required Packages:

With the virtual environment activated, install the packages listed in `requirements.txt`:

~~~bash
pip install -r requirements.txt
~~~

Note: If you're running this on a Windows system, you might need to replace `python-magic==0.4.22` with `python-magic-bin==0.4.14` in `requirements.txt` before running the `pip install -r requirements.txt` command. This is due to compatibility issues with the `python-magic` library on Windows.

## Usage

With everything set up, you can now use Repo2GPT:

~~~bash
python main.py <GitHub repository URL>
~~~

Replace `<GitHub repository URL>` with the URL of the repository you want to clone and analyze. 

Repo2GPT will generate a tree diagram of the repository's structure and a consolidated text file containing all the code in the repository. The files will be named `tree_diagram.txt` and `consolidated_code.txt`, respectively.


## Future plans

* Web version
* Ability to use repo2GPT on local folders
* Account for ignoring more types of irrelevant metadata files
* Add splitting of consolidated code into custom lengths

## License

Repo2GPT is licensed under the terms of the MIT license. See [LICENSE](LICENSE) for more details.


