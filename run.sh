#!/bin/bash

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

if [ $# -eq 0 ]
then
    echo "No arguments supplied. Usage: ./run.sh <GitHub repository URL>"
    exit 1
fi

python main.py $1

