# Contributing to Chronos MCP

First off, thank you for considering contributing to Chronos MCP! It's people like you that make Chronos MCP such a great tool.

## Code of Conduct

This project and everyone participating in it is governed by the [Chronos MCP Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code.

## How Can I Contribute?

### Reporting Bugs

Before creating bug reports, please check existing issues as you might find out that you don't need to create one. When you are creating a bug report, please include as many details as possible using our [bug report template](.github/ISSUE_TEMPLATE/bug_report.md).

### Suggesting Enhancements

Enhancement suggestions are tracked as GitHub issues. Create an issue using our [feature request template](.github/ISSUE_TEMPLATE/feature_request.md) and provide the following information:

* Use a clear and descriptive title
* Provide a step-by-step description of the suggested enhancement
* Provide specific examples to demonstrate the steps
* Describe the current behavior and explain which behavior you expected to see instead
* Explain why this enhancement would be useful

### Your First Code Contribution

Unsure where to begin contributing? You can start by looking through these `beginner` and `help-wanted` issues:

* [Beginner issues](https://github.com/democratize-technology/chronos-mcp/labels/beginner) - issues which should only require a few lines of code
* [Help wanted issues](https://github.com/democratize-technology/chronos-mcp/labels/help%20wanted) - issues which should be a bit more involved

### Development Setup

1. Fork the repo and create your branch from `main`:
   ```bash
   git clone https://github.com/your-username/chronos-mcp.git
   cd chronos-mcp
   git checkout -b feature/your-feature-name
   ```

2. Create a virtual environment and install dependencies:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -e ".[dev]"
   ```

3. Set up pre-commit hooks:
   ```bash
   pre-commit install
   ```

4. Create a test CalDAV server (optional, for integration testing):
   ```bash
   pip install radicale
   python -m radicale
   ```

### Pull Request Process

1. Ensure any install or build dependencies are removed before the end of the layer when doing a build.
2. Update the README.md with details of changes to the interface, including new environment variables, exposed ports, useful file locations, and container parameters.
3. Increase the version numbers in any examples files and the README.md to the new version that this Pull Request would represent. The versioning scheme we use is [SemVer](http://semver.org/).
4. You may merge the Pull Request once you have the sign-off of two other developers, or if you do not have permission to do that, you may request the second reviewer to merge it for you.

### Coding Standards

* We use [Black](https://black.readthedocs.io/) for code formatting
* We use [isort](https://pycqa.github.io/isort/) for import sorting
* We use [flake8](https://flake8.pycqa.org/) for linting
* We use [mypy](http://mypy-lang.org/) for type checking

Run all checks with:
```bash
make lint  # Runs all linters
make format  # Formats code with black and isort
make test  # Runs all tests
```

### Testing

* Write unit tests for all new functionality
* Ensure all tests pass before submitting PR
* Aim for >80% code coverage
* Test with multiple Python versions (3.10, 3.11, 3.12, 3.13)

### Documentation

* Use clear, descriptive variable names
* Add docstrings to all functions and classes
* Update README.md if adding new features
* Add inline comments for complex logic

### Commit Messages

We follow the [Conventional Commits](https://www.conventionalcommits.org/) specification:

* `feat:` New feature
* `fix:` Bug fix
* `docs:` Documentation changes
* `style:` Code style changes (formatting, missing semi-colons, etc)
* `refactor:` Code refactoring
* `perf:` Performance improvements
* `test:` Adding or updating tests
* `chore:` Maintenance tasks

Example:
```
feat: add support for recurring events

- Implement RRULE parsing
- Add recurrence UI in event creation
- Update event model to handle recurrence

Closes #123
```

### Security

* Never commit credentials or API keys
* Always sanitize error messages shown to users
* Validate all user inputs
* Follow OWASP guidelines for web security
* Report security vulnerabilities to contribute@democratize.technology

## Questions?

Feel free to open an issue with the `question` label or start a discussion on [GitHub Discussions](https://github.com/democratize-technology/chronos-mcp/discussions).

Thank you for contributing! 🎉
