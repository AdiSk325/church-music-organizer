# Contributing to Church Music Organizer

Thank you for your interest in contributing to Church Music Organizer! This document provides guidelines for contributing to the project.

## Getting Started

1. Fork the repository
2. Clone your fork locally
3. Create a new branch for your feature or bugfix
4. Make your changes
5. Test your changes
6. Submit a pull request

## Development Setup

```bash
# Clone the repository
git clone https://github.com/AdiSk325/church-music-organizer.git
cd church-music-organizer

# Install dependencies
pip install -r requirements.txt

# Install Tesseract OCR
# Ubuntu/Debian:
sudo apt-get install tesseract-ocr tesseract-ocr-pol tesseract-ocr-eng

# macOS:
brew install tesseract tesseract-lang

# Run the application
streamlit run src/app/main.py
```

## Code Style

- Follow PEP 8 guidelines for Python code
- Use meaningful variable and function names
- Add docstrings to functions and classes
- Keep functions focused and concise
- Add comments for complex logic

## Testing

Before submitting a pull request:

1. Run the integration test:
```bash
python test_integration.py
```

2. Run unit tests:
```bash
pytest tests/
```

3. Test the Streamlit interface manually

## Areas for Contribution

### High Priority
- Improved OCR accuracy for music notation
- Additional file format support
- Performance optimizations
- Better error handling
- More comprehensive tests

### Medium Priority
- User interface improvements
- Additional search filters
- Export functionality
- Batch operations
- Documentation improvements

### New Features
- Audio file support
- Advanced music analysis
- Cloud storage integration
- Mobile app version
- User authentication

## Submitting Changes

1. **Create a descriptive branch name**
   - Format: `feature/description` or `bugfix/description`
   - Example: `feature/audio-playback` or `bugfix/ocr-crash`

2. **Write clear commit messages**
   - Use present tense ("Add feature" not "Added feature")
   - First line: brief summary (50 chars or less)
   - Detailed description if needed

3. **Update documentation**
   - Update README.md if adding features
   - Update USAGE.md with examples
   - Add docstrings to new functions

4. **Test your changes**
   - Ensure existing tests pass
   - Add tests for new functionality
   - Test manually in the UI

5. **Submit a pull request**
   - Provide a clear description
   - Reference any related issues
   - Include screenshots for UI changes

## Code Review Process

1. Maintainers will review your PR
2. Address any feedback or requested changes
3. Once approved, your PR will be merged

## Reporting Bugs

When reporting bugs, please include:
- Description of the bug
- Steps to reproduce
- Expected behavior
- Actual behavior
- System information (OS, Python version, etc.)
- Error messages or logs

## Feature Requests

For feature requests:
- Describe the feature clearly
- Explain the use case
- Suggest a possible implementation
- Note any alternatives you've considered

## Questions?

Feel free to open an issue for questions or discussions.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.

Thank you for contributing to Church Music Organizer! 🎵
