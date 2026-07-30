# Contributing to CloudBackup for Windows

![Contributions Welcome](https://img.shields.io/badge/contributions-welcome-brightgreen.svg)
![License MIT](https://img.shields.io/badge/license-MIT-blue.svg)
![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)

Thank you for taking the time to contribute to CloudBackup for Windows! We are thrilled to welcome you to our open-source community. Whether you are fixing a small bug, improving documentation, or adding a major feature, your help makes this project better for everyone. This guide provides clear instructions to help you get started quickly and smoothly.

---

## 1. Ways to Contribute

You do not need to write code to contribute. Here are several ways you can help:

| Contribution Type | Description |
| :--- | :--- |
| **Bug Reports** | Identify and report issues or unexpected behavior. |
| **Feature Requests** | Suggest new ideas, storage providers, or usability improvements. |
| **Documentation** | Fix typos, clarify guides, or write tutorials for new users. |
| **Code Contributions** | Implement bug fixes, performance updates, or new engine features. |

---

## 2. How to Report a Bug

If you find a bug in CloudBackup for Windows, please open a GitHub Issue using our issue template.

Before creating a new bug report:
1. Search existing issues to ensure the problem has not already been reported.
2. Verify that you are running the latest version of CloudBackup for Windows.

When submitting a bug report, please include:
- A clear, descriptive issue title.
- Exact steps to reproduce the issue.
- Expected behavior versus actual behavior.
- System information (Windows version, Python version, rclone version).
- Relevant, sanitized log outputs without personal credentials or tokens.

> [!IMPORTANT]
> Never post sensitive security data, API keys, passwords, or personal names in public issue tracker reports.

---

## 3. How to Suggest a Feature

We welcome new feature requests! To submit a feature suggestion:
1. Open a new issue on GitHub and select the feature request option.
2. Use a concise and descriptive title.
3. Describe the problem or use case your proposed feature addresses.
4. Explain how the feature should work in step-by-step detail.
5. Provide any relevant examples or mockups if applicable.

---

## 4. Development Setup

Follow these steps to set up your local development environment:

1. **Fork the Repository**  
   Click the **Fork** button at the top right of the repository page on GitHub.
2. **Clone Your Fork**  
   Clone your fork to your local machine:
   ```bash
   git clone https://github.com/your-username/cloudbackup-windows.git
   cd cloudbackup-windows
   ```
3. **Create a Virtual Environment**  
   Set up an isolated Python virtual environment:
   ```bash
   python -m venv venv
   venv\Scripts\activate
   ```
4. **Install Dependencies**  
   Install all required development packages:
   ```bash
   pip install -r requirements.txt
   ```

---

## 5. Code Style Guidelines

To keep the codebase clean, consistent, and readable, please follow these guidelines:

- **PEP 8 Compliance**: Follow standard Python PEP 8 formatting rules.
- **Naming Conventions**: Use `snake_case` for functions and variables, and `PascalCase` for classes.
- **Clear Code**: Write short, readable functions with clear parameter names.
- **Documentation**: Include descriptive docstrings for functions, classes, and complex logic blocks.
- **Type Annotations**: Use Python type hints wherever possible to improve code clarity.

> [!TIP]
> Run `flake8` or `black` before committing code to format your files automatically.

---

## 6. How to Submit a Pull Request

Follow these steps to submit your code changes:

1. **Create a Topic Branch**  
   Create a descriptive branch for your work:
   ```bash
   git checkout -b feature/add-new-provider
   ```
2. **Make Your Changes**  
   Implement your changes clearly and add unit tests when applicable.
3. **Commit Your Work**  
   Write clean, descriptive commit messages:
   ```bash
   git commit -m "feat: add support for S3 compatible endpoints"
   ```
4. **Push to GitHub**  
   Push your feature branch to your fork:
   ```bash
   git push origin feature/add-new-provider
   ```
5. **Open a Pull Request**  
   Navigate to the main repository on GitHub and click **Compare & pull request**.

---

## 7. What Makes a Good PR?

A well-prepared Pull Request speeds up the review process. Please ensure your PR:
- References any related GitHub issue (for example, `Fixes #42`).
- Keeps changes focused on a single feature or bug fix.
- Includes updated documentation and tests.
- Passes all automated build tests and linters.
- Explains the motivation behind the implementation choices.

---

## 8. Code of Conduct

We are committed to providing a friendly, safe, and welcoming environment for everyone. Please be respectful and constructive in all communications, reviews, and issue discussions.

> [!NOTE]
> All project participants are expected to adhere to our community standards and treat fellow contributors with respect.

---

## 9. Thank You!

Your contributions make CloudBackup for Windows a robust tool for everyone. We appreciate your time, effort, and support in making this open-source project better!

