from setuptools import setup, find_packages

setup(
    name="cognit-vcs",
    version="0.1.0",
    description="Cognit: An Intelligent, Agent-Native Version Control System",
    long_description=open("README.md", encoding="utf-8").read() if open("README.md", "r") else "",
    long_description_content_type="text/markdown",
    author="Cognit Community",
    packages=find_packages(),
    python_requires=">=3.8",
    entry_points={
        "console_scripts": [
            "cognit=cognit.cli:main",
            "cog=cognit.cli:main",
        ],
    },
)
