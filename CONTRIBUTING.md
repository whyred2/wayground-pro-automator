# Contributing to Wayground Pro Automator

This document outlines the guidelines and steps to help you get started.

## 🛠️ How to Report a Bug or Suggest a Feature

Before creating a new Issue, please follow these steps:

1. **Check Existing Issues**: Ensure your bug or idea hasn't already been reported or discussed.
2. **Provide Detail**: When opening an issue, please include:
   - **Python Version**: (`python --version`)
   - **Operating System**: (Windows, macOS, Linux)
   - **Steps to Reproduce**: A clear list of actions leading to the bug.
   - **Expected vs. Actual Behavior**: What did you expect to happen, and what actually happened?
   - **Logs/Screenshots**: Terminal output or the `error_debug.png` file (attach manually).

## 💻 Pull Request (PR) Process

If you want to fix a bug or add a new feature yourself:

1. **Fork the Repository**: Create your own copy of the project.
2. **Clone it Locally**:
   ```powershell
   git clone https://github.com/whyred2/wayground-pro-automator.git
   cd wayground-pro-automator
   ```
3. **Create a Branch**:
   ```powershell
   git checkout -b feature/your-feature-name
   # or
   git checkout -b fix/bug-description
   ```
4. **Set Up the Environment**:
   ```powershell
   pip install -r requirements.txt
   python -m playwright install chromium
   ```
5. **Implement Your Changes**: Ensure your logic aligns with the existing project architecture.
6. **Test Thoroughly**: Verify that core features (automation, network interception, answer matching) remain stable.
7. **Commit Your Changes**: Use clear, descriptive commit messages (e.g., Conventional Commits):
   ```powershell
   git commit -m "feat: add smart parsing for new question types"
   ```
8. **Push to Your Fork**:
   ```powershell
   git push origin feature/your-feature-name
   ```
9. **Open a Pull Request**: Submit your PR to the original repository. Describe what you fixed or added in detail.

## 📝 Code Style & Requirements

To keep the codebase clean and maintainable, please follow these rules:

- **Language**: Python 3.10+. Feel free to use modern features like `match-case`.
- **Type Hinting**: We strongly recommend adding type annotations to all new functions and methods.
- **Documentation**: Complex logic (especially Playwright interactions or API interception) should be well-commented.
- **Coding Standards (PEP 8)**: Please keep the code tidy. We recommend using formatters like `Black` or your IDE's built-in linters.
- **Naming Conventions**: Use English for all variable, function, and class names. Use descriptive names (e.g., `intercept_test_payload()` instead of `do_it()`).

## ⚠️ Disclaimer

As stated in the License and `README.md`, this project is for educational purposes only. By contributing, you guarantee that your code does not contain destructive logic (e.g., DDoS-like requests or scraping intended to harm the platform).

## 🤝 Questions?

If you have ideas for architectural refactoring or are unsure about a large feature, please open an Issue with the `enhancement` or `discussion` label. Let's talk about it before you spend too much time on the code!
