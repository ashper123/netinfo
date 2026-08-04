# Contributing to netinfo

Thank you for your interest in contributing to the **Network Information Toolkit (netinfo)**!

## Architecture Philosophy

1. **Single File core (`netinfo.py`)**: The project deliberately maintains zero mandatory external dependencies for core CLI execution.
2. **Backward Compatibility**: Existing console output layout and JSON schema keys are locked. Additive changes only.
3. **Cross-Platform Parity**: Every feature must work seamlessly across Windows, Linux, and macOS without throwing unhandled exceptions.

## Development Workflow

1. Fork and clone the repository:
   ```bash
   git clone https://github.com/your-username/netinfo.git
   cd netinfo
   ```
2. Install development dependencies:
   ```bash
   pip install -r requirements-dev.txt
   ```
3. Run the test suite:
   ```bash
   pytest
   ```
4. Verify code coverage:
   ```bash
   coverage run -m pytest
   coverage report -m
   ```

## Pull Request Guidelines

- Ensure all new features are covered by unit tests in `tests/`.
- Ensure non-zero exit codes are never raised for missing network hardware or offline interfaces.
- Format code cleanly following PEP 8 conventions.
